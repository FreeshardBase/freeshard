import logging

from fastapi import APIRouter, Cookie, HTTPException, status
from fastapi.responses import Response

from shard_core.data_model.user import InputUser, OutputUser, User
from shard_core.database import users as db_users
from shard_core.database.connection import db_conn
from shard_core.service import owner_email, pairing
from shard_core.util.misc import SlidingWindow

log = logging.getLogger(__name__)

# Every confirmation mail costs the controller a real send, and both routes that
# trigger one share the budget — otherwise alternating between them doubles it.
_email_send_limit = SlidingWindow(limit=5, window=3600)

router = APIRouter(
    prefix="/users",
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
    if user is None or user.disabled:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED)
    return user


@router.get("/me", response_model=OutputUser)
async def get_me(authorization: str = Cookie(None)):
    return OutputUser.from_user(await _session_user(authorization))


@router.patch("/me", response_model=OutputUser)
async def patch_me(update: InputUser, authorization: str = Cookie(None)):
    user = await _session_user(authorization)
    fields = update.model_dump(exclude_unset=True)

    if update.display_name is not None:
        async with db_conn() as conn:
            user = await db_users.update(
                conn, user.id, {"display_name": update.display_name}
            )

    # an omitted email is untouched, an explicit null clears it — which
    # model_dump alone cannot tell apart
    if "email" in fields:
        if update.email is None:
            user = await owner_email.clear_email(user)
        else:
            if _email_send_limit.is_exceeded():
                raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS)
            try:
                user = await owner_email.set_email(user, update.email)
            except owner_email.DeliveryFailed:
                raise HTTPException(
                    status.HTTP_502_BAD_GATEWAY,
                    detail="The address was saved but the confirmation email could "
                    "not be sent. Try sending it again in a moment.",
                )

    return OutputUser.from_user(user)


@router.post(
    "/me/email/resend",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def resend_confirmation(authorization: str = Cookie(None)):
    user = await _session_user(authorization)
    if _email_send_limit.is_exceeded():
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS)
    try:
        await owner_email.resend_verification(user)
    except owner_email.NoPendingEmail:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, detail="No address is waiting for confirmation."
        )
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
    await owner_email.discard_pending(user)
