"""The owner's email address: setting it, confirming it, clearing it.

The invariant this module exists to keep is what makes the OIDC `email_verified`
claim mean something: **users.email is always verified, users.pending_email is
an unverified candidate**. A new address goes to pending_email and only moves to
email once the owner has opened a link that was delivered to it. At most one
candidate is in flight per user; a superseded one is simply replaced.

The shard mints and checks the confirmation token itself. The controller is only
asked to deliver mail — it never learns what the token unlocks. A self-hosted
shard has no controller and therefore no mail at all, which is why
`oidc.email_verification = false` sets the address directly instead.
"""

import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone

from shard_core.data_model.user import User
from shard_core.database import users as db_users
from shard_core.database.connection import db_conn
from shard_core.service import freeshard_controller
from shard_core.settings import settings

log = logging.getLogger(__name__)

# The token alone completes the change, so it is the credential and its lifetime
# is the exposure. An hour covers mail delivery and a distracted owner; resend
# is one click.
TOKEN_LIFETIME = timedelta(hours=1)

_CLEARED_PENDING = {
    "pending_email": None,
    "email_token_hash": None,
    "email_token_expires": None,
}


class NoPendingEmail(Exception):
    pass


class DeliveryFailed(Exception):
    pass


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def set_email(user: User, address: str) -> User:
    """Take an address as the owner's new one.

    With verification enabled the address becomes the candidate and a link is
    sent to it; the current address is untouched until that link is opened.
    Without verification there is no way to send the link, so the address is
    taken as-is.
    """
    if not settings().oidc.email_verification:
        async with db_conn() as conn:
            updated = await db_users.update(
                conn, user.id, {"email": address, **_CLEARED_PENDING}
            )
        await _mirror_to_controller(address)
        log.info(f"set the address of {updated} without verification")
        return updated

    token = secrets.token_urlsafe(32)
    async with db_conn() as conn:
        updated = await db_users.update(
            conn,
            user.id,
            {
                "pending_email": address,
                "email_token_hash": hash_token(token),
                "email_token_expires": datetime.now(timezone.utc) + TOKEN_LIFETIME,
            },
        )
    await _deliver_verification(address, token)
    return updated


async def resend_verification(user: User) -> None:
    """Send a fresh link for the candidate already on file.

    The previous token is replaced rather than re-sent: it is stored as a digest
    and cannot be recovered.
    """
    if user.pending_email is None:
        raise NoPendingEmail
    token = secrets.token_urlsafe(32)
    async with db_conn() as conn:
        await db_users.update(
            conn,
            user.id,
            {
                "email_token_hash": hash_token(token),
                "email_token_expires": datetime.now(timezone.utc) + TOKEN_LIFETIME,
            },
        )
    await _deliver_verification(user.pending_email, token)


async def discard_pending(user: User) -> User:
    async with db_conn() as conn:
        return await db_users.update(conn, user.id, dict(_CLEARED_PENDING))


async def clear_email(user: User) -> User:
    """Drop the address entirely, telling the old one first.

    No address is a valid state — it is where every shard lands after the 0005
    migration — but a hijacked session must not be able to remove the owner's
    contact channel without the real owner hearing about it.
    """
    if settings().oidc.email_verification:
        await _notify(
            "The contact address for your Freeshard is being removed",
            [
                "The contact address for your Freeshard was just removed, so we can "
                "no longer reach you about your shard — storage warnings, billing "
                "notices and service messages included.",
                "If this was not you, open your terminal and set an address again.",
            ],
        )
    async with db_conn() as conn:
        updated = await db_users.update(
            conn, user.id, {"email": None, **_CLEARED_PENDING}
        )
    await _mirror_to_controller(None)
    log.info(f"cleared the address of {updated}")
    return updated


async def confirm_email(token: str) -> bool:
    """Promote the candidate belonging to *token*, if the token is still valid.

    Returns whether anything was promoted. Callers must not pass that on to an
    unauthenticated client: the answer says whether an address is pending.
    """
    user = await _user_for_token(token)
    if user is None:
        return False

    await _notify(
        "The contact address for your Freeshard is changing",
        [
            f"The contact address for your Freeshard was just changed to "
            f"{user.pending_email}. This is the last message going to this address.",
            "If this was not you, open your terminal and set the address back.",
        ],
    )

    address = user.pending_email
    async with db_conn() as conn:
        updated = await db_users.update(
            conn, user.id, {"email": address, **_CLEARED_PENDING}
        )
    log.info(f"confirmed the address of {updated}")

    if await _mirror_to_controller(address):
        await _notify(
            "Your Freeshard contact address is confirmed",
            [
                "This address is now the contact address for your Freeshard.",
                "Messages about your shard arrive here from now on.",
            ],
        )
    return True


async def _user_for_token(token: str) -> User | None:
    digest = hash_token(token)
    now = datetime.now(timezone.utc)
    async with db_conn() as conn:
        candidates = await db_users.get_all_with_pending_email_token(conn)
    for user in candidates:
        if not secrets.compare_digest(user.email_token_hash, digest):
            continue
        if user.email_token_expires is None or user.email_token_expires < now:
            log.info(f"rejected an expired confirmation token for {user}")
            return None
        if user.pending_email is None:
            return None
        return user
    return None


async def _deliver_verification(address: str, token: str):
    try:
        await freeshard_controller.send_verification_email(address, token)
    except Exception as e:
        log.error(f"could not send a verification email: {e}")
        raise DeliveryFailed from e


async def _mirror_to_controller(address: str | None) -> bool:
    """Best effort: the shard owns the address, the controller only mirrors it."""
    try:
        await freeshard_controller.set_owner_email(address)
    except Exception as e:
        log.error(f"could not mirror the owner address to the controller: {e}")
        return False
    return True


async def _notify(subject: str, body: list[str]):
    """Best effort: a failed courtesy message must not block the change."""
    try:
        await freeshard_controller.relay_email_to_owner(subject, body)
    except Exception as e:
        log.error(f"could not notify the owner about an address change: {e}")
