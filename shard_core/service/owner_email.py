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
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum

from shard_core.data_model.user import User
from shard_core.database import preferences as db_preferences
from shard_core.database import users as db_users
from shard_core.database.connection import db_conn
from shard_core.service import freeshard_controller
from shard_core.settings import settings
from shard_core.util import signals
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


class TokenStatus(str, Enum):
    """Outcome of redeeming a confirmation token. All three are safe to hand
    an unauthenticated caller: reaching EXPIRED already requires the real
    256-bit token to have matched a stored digest at some point, which costs a
    guesser exactly as much as reaching CONFIRMED does — nothing distinguishes
    EXPIRED from UNKNOWN that a guesser could exploit. Decided with Max,
    2026-11-26, as the deliberate successor to the previous always-204 design."""

    UNKNOWN = "unknown"
    EXPIRED = "expired"
    CONFIRMED = "confirmed"


@dataclass
class ConfirmResult:
    status: TokenStatus
    email: str | None = None


@dataclass(frozen=True)
class _Notice:
    subject: str
    body: list[str]


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
            updated = await db_users.update(conn, user.id, {"email": address, **_CLEARED_PENDING})
        signals.on_owner_user_changed.send(updated)
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
    signals.on_owner_user_changed.send(updated)
    await _deliver_verification(address, token, await _stored_language(user.id))
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
    await _deliver_verification(user.pending_email, token, await _stored_language(user.id))


async def discard_pending(user: User) -> User:
    async with db_conn() as conn:
        updated = await db_users.update(conn, user.id, dict(_CLEARED_PENDING))
    signals.on_owner_user_changed.send(updated)
    return updated


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
        await _notify(_removal_notice(await _stored_language(user.id)))
    async with db_conn() as conn:
        updated = await db_users.update(conn, user.id, {"email": None, **_CLEARED_PENDING})
    signals.on_owner_user_changed.send(updated)
    await _mirror_to_controller(None)
    log.info(f"cleared the address of {updated}")
    return updated


async def confirm_email(token: str) -> ConfirmResult:
    """Promote the candidate belonging to *token*, if the token is still valid.

    The token is spent before anything else happens, so the notification and the
    controller calls in the middle cannot be replayed by a second click. The
    old address is told before the switch is mirrored, because the controller's
    relay only ever reaches the address it currently has on file — but only
    when there was an old address: every shard starts with email = None (the
    0005-migration invariant), so a user's very first confirmation has nothing
    to warn away from, and sending that notice there just duplicates the
    "confirmed" one that follows, usually to the very same inbox.

    Returns a ConfirmResult; see TokenStatus for which parts are safe to show
    an unauthenticated caller. A candidate that moved on between the token
    being spent and the promotion (vanishingly rare: another confirmation or a
    fresh set_email in the same instant) is reported as EXPIRED — it is the
    same "this one isn't live any more" fact the owner needs, not a new case.
    """
    status, claimed = await _claim_token(token)
    if status != TokenStatus.CONFIRMED:
        return ConfirmResult(status=status)

    address = claimed.pending_email
    language = await _stored_language(claimed.id)
    if claimed.email is not None:
        await _notify(_change_notice(language, address))

    async with db_conn() as conn:
        updated = await db_users.promote_pending_email(conn, claimed.id, address)
    if updated is None:
        log.info(f"candidate of user {claimed.id} moved on before its link was opened")
        return ConfirmResult(status=TokenStatus.EXPIRED)
    signals.on_owner_user_changed.send(updated)
    log.info(f"confirmed the address of {updated}")

    if await _mirror_to_controller(address):
        await _notify(_confirmed_notice(language))
    return ConfirmResult(status=TokenStatus.CONFIRMED, email=address)


async def _claim_token(token: str) -> tuple[TokenStatus, User | None]:
    """Find the user whose token this is and spend it, in that order.

    The digest is matched in Python with a constant-time comparison rather than
    looked up in SQL, so the match itself is not a timing oracle; the spending
    is then a single conditional UPDATE, which is what makes it single-use.

    UNKNOWN (no stored digest matches) and EXPIRED (one did, but the UPDATE's
    own expiry/candidate guard rejected it) are deliberately told apart here —
    matching a digest at all already requires the real token, so a guesser
    gets nothing from the distinction that a 256-bit random value didn't
    already deny them.
    """
    digest = hash_token(token)
    async with db_conn() as conn:
        candidates = await db_users.get_all_with_pending_email_token(conn)
        for user in candidates:
            if not secrets.compare_digest(user.email_token_hash, digest):
                continue
            claimed = await db_users.claim_email_token(conn, user.id, digest)
            if claimed is None:
                log.info(f"rejected an expired confirmation token for {user}")
                return TokenStatus.EXPIRED, None
            return TokenStatus.CONFIRMED, claimed
    return TokenStatus.UNKNOWN, None


def _require_send_budget():
    """Charge the mail budget before anything is written.

    Charging after the write would let a refused request replace the token of a
    candidate whose link is already in the owner's inbox.
    """
    if not _send_limit.try_acquire():
        raise SendRateLimited


async def _stored_language(user_id: int) -> str | None:
    async with db_conn() as conn:
        prefs = await db_preferences.get(conn, user_id)
    return prefs.language


async def _deliver_verification(address: str, token: str, language: str | None):
    try:
        await freeshard_controller.send_verification_email(address, token, language)
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


async def _notify(notice: _Notice):
    """Best effort: a failed courtesy message must not block the change."""
    try:
        await freeshard_controller.relay_email_to_owner(notice.subject, notice.body)
    except Exception as e:
        log.error(f"could not notify the owner about an address change: {e}")


# Each notice falls back to "en" for an unrecognised or missing language
# (None included), matching the convention the controller already applies to
# the verification mail's own `language` field.


def _removal_notice(language: str | None) -> _Notice:
    notices = {
        "en": _Notice(
            "The contact address for your Shard is being removed",
            [
                "The contact address for your Shard was just removed, so we can "
                "no longer reach you about your shard — storage warnings, billing "
                "notices and service messages included.",
                "If this was not you, open your terminal and set an address again.",
            ],
        ),
        "de": _Notice(
            "Die Kontaktadresse deines Shards wird entfernt",
            [
                "Die Kontaktadresse deines Shards wurde gerade entfernt. Deshalb "
                "können wir dich nicht mehr erreichen, wenn es um deinen Shard "
                "geht, auch nicht für Speicherwarnungen, Hinweise zur Abrechnung "
                "oder Servicemitteilungen.",
                "Falls du das nicht warst, öffne deinen Shard und hinterlege wieder eine Adresse.",
            ],
        ),
    }
    return notices.get(language, notices["en"])


def _change_notice(language: str | None, address: str) -> _Notice:
    notices = {
        "en": _Notice(
            "The contact address for your Shard is changing",
            [
                f"The contact address for your Shard was just changed to "
                f"{address}. This is the last message going to this address.",
                "If this was not you, open your terminal and set the address back.",
            ],
        ),
        "de": _Notice(
            "Die Kontaktadresse deines Shards ändert sich",
            [
                f"Die Kontaktadresse deines Shards wurde gerade auf {address} "
                f"geändert. Das ist die letzte Nachricht an diese Adresse.",
                "Falls du das nicht warst, öffne deinen Shard und trage die alte Adresse wieder ein.",
            ],
        ),
    }
    return notices.get(language, notices["en"])


def _confirmed_notice(language: str | None) -> _Notice:
    notices = {
        "en": _Notice(
            "Your Shard contact address is confirmed",
            [
                "This address is now the contact address for your Shard.",
                "Messages about your shard arrive here from now on.",
            ],
        ),
        "de": _Notice(
            "Die Kontaktadresse deines Shards ist bestätigt",
            [
                "Diese Adresse ist jetzt die Kontaktadresse deines Shards.",
                "Nachrichten zu deinem Shard kommen ab jetzt hier an.",
            ],
        ),
    }
    return notices.get(language, notices["en"])
