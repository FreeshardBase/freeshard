import logging

from fastapi import APIRouter, Cookie, HTTPException, status
from fastapi.responses import Response

from shard_core.data_model.user import InputUser, OutputUser, Role, User
from shard_core.database import users as db_users
from shard_core.database.connection import db_conn
from shard_core.service import owner_email, pairing

log = logging.getLogger(__name__)

router = APIRouter(
    prefix="/users",
)

# Everything the address routes touch is owner-global: the controller relay
# mails the shard's registered owner and the mirror rewrites shards.owner_email.
# Every terminal binds to the owner today, so this only fires once members exist
# — which is exactly when a member editing their own address must stop
# redirecting the owner's billing mail.
_OWNER_ONLY = "Only the shard owner's address can be set from here."
_SEND_LIMITED = "Too many confirmation emails requested. Try again later."
_DELIVERY_FAILED = (
    "The address was saved but the confirmation email could not be sent. "
    "Send it again in a moment."
)


async def _session_user(authorization: str | None) -> User:
    """The user behind the terminal session this request carries.

    Traefik has already established that the cookie is valid before the request
    reaches /protected; reading it again here is what resolves *which* user is
    asking, which is the part forwardAuth cannot answer.
    """
    if not authorization:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED)
    try:
        terminal = await pairing.verify_terminal_jwt(authorization)
    except pairing.InvalidJwt:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED)
    async with db_conn() as conn:
        user = await db_users.get_by_id(conn, terminal.user_id)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED)
    if user.disabled:
        # authenticated, but not allowed — re-authenticating would not help
        raise HTTPException(status.HTTP_403_FORBIDDEN)
    return user


def _owner_or_403(user: User):
    if user.role is not Role.OWNER:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail=_OWNER_ONLY)


# NOTE: /me is a literal path. Any future /{id} route must be declared after it,
# or it swallows /me.
@router.get("/me", response_model=OutputUser)
async def get_me(authorization: str = Cookie(None)):
    return OutputUser.from_user(await _session_user(authorization))


@router.patch("/me", response_model=OutputUser)
async def patch_me(update: InputUser, authorization: str = Cookie(None)):
    user = await _session_user(authorization)
    # an omitted field is untouched, an explicit null clears it — which the
    # Optional annotation alone cannot tell apart
    fields = update.model_dump(exclude_unset=True)

    if "display_name" in fields:
        if update.display_name is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="display_name cannot be null.",
            )
        async with db_conn() as conn:
            user = await db_users.update(
                conn, user.id, {"display_name": update.display_name}
            )

    if "email" in fields:
        _owner_or_403(user)
        user = await _apply_email(user, update.email)

    return OutputUser.from_user(user)


async def _apply_email(user: User, address: str | None) -> User:
    if address is None:
        return await owner_email.clear_email(user)
    try:
        return await owner_email.set_email(user, address)
    except owner_email.SendRateLimited:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, detail=_SEND_LIMITED)
    except owner_email.DeliveryFailed:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail=_DELIVERY_FAILED)


@router.post(
    "/me/email/resend",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def resend_confirmation(authorization: str = Cookie(None)):
    user = await _session_user(authorization)
    _owner_or_403(user)
    try:
        await owner_email.resend_verification(user)
    except owner_email.NoPendingEmail:
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail="No address is waiting for confirmation."
        )
    except owner_email.VerificationDisabled:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="This shard does not send confirmation email.",
        )
    except owner_email.SendRateLimited:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, detail=_SEND_LIMITED)
    except owner_email.DeliveryFailed:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            detail="The confirmation email could not be sent.",
        )


@router.delete(
    "/me/email/pending",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_pending_email(authorization: str = Cookie(None)):
    user = await _session_user(authorization)
    _owner_or_403(user)
    await owner_email.discard_pending(user)
