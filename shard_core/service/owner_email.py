"""The owner's email address: setting it, confirming it, clearing it.

The invariant this module exists to keep is what makes the OIDC `email_verified`
claim mean something: **users.email is always verified, users.pending_email is
an unverified candidate**. A new address goes to pending_email and only moves to
email once the owner has opened a link that was delivered to it. At most one
candidate is in flight per user; a superseded one is simply replaced.

The shard mints and checks the confirmation token itself. The controller is only
asked to deliver mail — it never learns what the token unlocks. A self-hosted
shard has no controller and therefore no mail at all, which is why
`email.enabled = false` sets the address directly instead.
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
from shard_core.util.misc import SlidingWindow

log = logging.getLogger(__name__)

# The token alone completes the change, so it is the credential and its lifetime
# is the exposure. An hour covers mail delivery and a distracted owner; resend
# is one click.
TOKEN_LIFETIME = timedelta(hours=1)

# Every confirmation mail costs the controller a real send, so the budget sits
# here rather than on either route — otherwise alternating between setting an
# address and resending doubles it. Only a send that is actually attempted is
# charged, so a shard that cannot send mail at all is not rationed.
_send_limit = SlidingWindow(limit=5, window=3600)

_CLEARED_PENDING = {
    "pending_email": None,
    "email_token_hash": None,
    "email_token_expires": None,
}


class NoPendingEmail(Exception):
    pass


class DeliveryFailed(Exception):
    pass


class SendRateLimited(Exception):
    pass


class VerificationDisabled(Exception):
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
    if not settings().email.enabled:
        async with db_conn() as conn:
            updated = await db_users.update(
                conn, user.id, {"email": address, **_CLEARED_PENDING}
            )
        await _mirror_to_controller(address)
        log.info(f"set the address of {updated} without verification")
        return updated

    _require_send_budget()
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
    if not settings().email.enabled:
        raise VerificationDisabled
    if user.pending_email is None:
        raise NoPendingEmail
    _require_send_budget()
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

    Clearing what is already empty is not that, and must stay a no-op: after the
    0005 migration every shard has no address while the controller still holds
    the signup one, and mirroring a null there is what stops disk, billing and
    wind-down mail from ever reaching the owner again.
    """
    if user.email is None and user.pending_email is None:
        return user

    if settings().email.enabled:
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

    The token is spent before anything else happens, so the notification and the
    controller calls in the middle cannot be replayed by a second click. The
    old address is told before the switch is mirrored, because the controller's
    relay only ever reaches the address it currently has on file.

    Returns whether anything was promoted. Callers must not pass that on to an
    unauthenticated client: the answer says whether an address was pending.
    """
    claimed = await _claim_token(token)
    if claimed is None:
        return False

    address = claimed.pending_email
    await _notify(
        "The contact address for your Freeshard is changing",
        [
            f"The contact address for your Freeshard was just changed to "
            f"{address}. This is the last message going to this address.",
            "If this was not you, open your terminal and set the address back.",
        ],
    )

    async with db_conn() as conn:
        updated = await db_users.promote_pending_email(conn, claimed.id, address)
    if updated is None:
        log.info(f"candidate of user {claimed.id} moved on before its link was opened")
        return False
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


async def _claim_token(token: str) -> User | None:
    """Find the user whose token this is and spend it, in that order.

    The digest is matched in Python with a constant-time comparison rather than
    looked up in SQL, so the match itself is not a timing oracle; the spending
    is then a single conditional UPDATE, which is what makes it single-use.
    """
    digest = hash_token(token)
    async with db_conn() as conn:
        candidates = await db_users.get_all_with_pending_email_token(conn)
        for user in candidates:
            if not secrets.compare_digest(user.email_token_hash, digest):
                continue
            claimed = await db_users.claim_email_token(conn, user.id, digest)
            if claimed is None:
                log.info(f"rejected a spent or expired confirmation token for {user}")
            return claimed
    return None


def _require_send_budget():
    """Charge the mail budget before anything is written.

    Charging after the write would let a refused request replace the token of a
    candidate whose link is already in the owner's inbox.
    """
    if not _send_limit.try_acquire():
        raise SendRateLimited


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
