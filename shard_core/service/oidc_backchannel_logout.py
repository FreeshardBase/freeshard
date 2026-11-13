"""Delivery of OIDC Back-Channel Logout 1.0 notifications to installed apps.

A relying party like Immich mints its own app-local session at the OAuth
callback and never re-checks the IdP, so revoking the shard's own tokens on
un-pair changes nothing for a browser or phone that is already logged in.
This module closes that gap by pushing a logout_token to the app.

Enqueue happens synchronously inside the un-pair transaction
(web/protected/terminals.py, see enqueue_for_terminal): the terminal's live
(unrevoked) OIDC grants are read and one outbox row is written per
(client_id, sid) that has somewhere to go, BEFORE oidc.revoke_for_terminal
marks those grants revoked and before the terminals row disappears (its FK is
ON DELETE SET NULL — the linkage is gone afterwards).

Delivery is out-of-band and durable: migration shard-core-0008 gives the
outbox a table, not an in-memory queue, so a row survives a restart and is
simply picked up by the next drain.

drain_due_outbox() attempts delivery of every outbox entry that is due and
whose owning app is currently RUNNING (claim_due_outbox_entries bakes that
filter in — a stopped app is never woken just to receive its own logout).
Claiming is atomic (FOR UPDATE SKIP LOCKED, see database.oidc) because this
module's two drain triggers are independent and uncoordinated, so overlapping
drains are routine, not a theoretical edge case. It is driven by two
triggers, both calling the same function:
  * the on_apps_update signal (connected below), which fires on every app
    status write — draining then is a no-op unless some due row's app just
    became RUNNING;
  * a PeriodicTask backstop (app_factory.py), for bounded retries whose
    backoff elapses without any app status changing in between.

The logout_token is minted fresh on every delivery attempt
(oidc_provider.sign_logout_token), never cached from enqueue time: a relying
party may reject a token whose age exceeds its own tolerance, so a token
signed at un-pair and retried minutes later could be rejected even though
delivery itself went through.
"""

import logging
from datetime import datetime, timedelta, timezone

import httpx

from shard_core.database import oidc as db_oidc
from shard_core.database.connection import db_conn
from shard_core.service import oidc_provider
from shard_core.util import signals

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 5
# Backoff in seconds before each retry; index = attempts already made - 1,
# clamped to the last entry once attempts exceed the table.
RETRY_DELAYS_SECONDS = [30, 60, 300, 900, 3600]
DELIVERY_TIMEOUT = 10


async def enqueue_for_terminal(conn, terminal_id: str) -> None:
    """Snapshot the terminal's live grants and enqueue a delivery for each
    one whose client has a backchannel_logout_uri.

    Caller contract: must run on the SAME connection/transaction as, and
    strictly before, both oidc.revoke_for_terminal (which marks the grants
    read here as revoked) and terminals.remove (whose ON DELETE SET NULL on
    oidc_tokens.terminal_id severs the only way to find them). See
    web/protected/terminals.py::delete_terminal_by_id.
    """
    grants = await db_oidc.get_live_grants_for_terminal(conn, terminal_id)
    await db_oidc.enqueue_backchannel_logout(conn, terminal_id, grants)


def _next_delay_seconds(attempts_made: int) -> int:
    idx = min(attempts_made - 1, len(RETRY_DELAYS_SECONDS) - 1)
    return RETRY_DELAYS_SECONDS[max(idx, 0)]


async def _post_logout_token(url: str, token: str) -> None:
    """The network call, factored out so tests can patch it directly instead
    of mocking the httpx client machinery."""
    async with httpx.AsyncClient(timeout=DELIVERY_TIMEOUT) as client:
        response = await client.post(url, data={"logout_token": token})
    response.raise_for_status()


async def _attempt_delivery(entry: dict) -> None:
    if not entry.get("backchannel_logout_uri"):
        # The claim is live-joined against oidc_clients, not a snapshot
        # taken at enqueue time, so a reinstall/update landing inside the
        # retry window can null this out from under an already-queued row
        # (register_client overwrites it on every re-registration). There is
        # nowhere to deliver to any more -- fail now rather than retry
        # forever, since nothing about this condition fixes itself with time.
        async with db_conn() as conn:
            error = "client no longer declares a backchannel_logout_uri"
            log.error(
                "backchannel logout delivery to app %s (client %s, sid %s) failed permanently: %s",
                entry["app_name"],
                entry["client_id"],
                entry["sid"],
                error,
            )
            await db_oidc.mark_outbox_failed(conn, entry["id"], entry["attempts"] + 1, error)
        return

    await oidc_provider.ensure_configured()
    token = oidc_provider.sign_logout_token(client_id=entry["client_id"], user_sub=entry["user_sub"], sid=entry["sid"])
    error = None
    try:
        await _post_logout_token(entry["backchannel_logout_uri"], token)
    except Exception as e:
        # Deliberately not narrowed to httpx.HTTPError: ANY failure to
        # deliver must flow through the retry bookkeeping below. A narrower
        # catch here lets an unanticipated exception type (e.g. a TypeError
        # from a malformed URL) escape to drain_due_outbox's batch-level
        # catch-all, which only logs -- it cannot update next_attempt_at/
        # status, so the row would stay due and retry on every drain
        # forever, uncapped.
        error = f"{type(e).__name__}: {e}"

    async with db_conn() as conn:
        if error is None:
            await db_oidc.mark_outbox_delivered(conn, entry["id"])
            return
        attempts = entry["attempts"] + 1
        if attempts >= MAX_ATTEMPTS:
            log.error(
                "backchannel logout delivery to app %s (client %s, sid %s) failed permanently after %d attempts: %s",
                entry["app_name"],
                entry["client_id"],
                entry["sid"],
                attempts,
                error,
            )
            await db_oidc.mark_outbox_failed(conn, entry["id"], attempts, error)
        else:
            delay = _next_delay_seconds(attempts)
            next_attempt_at = datetime.now(timezone.utc) + timedelta(seconds=delay)
            log.warning(
                "backchannel logout delivery to app %s (client %s, sid %s) failed (attempt %d/%d), retrying in %ds: %s",
                entry["app_name"],
                entry["client_id"],
                entry["sid"],
                attempts,
                MAX_ATTEMPTS,
                delay,
                error,
            )
            await db_oidc.mark_outbox_retry(conn, entry["id"], attempts, next_attempt_at, error)


async def drain_due_outbox(app_name: str | None = None) -> None:
    """Attempt delivery of every outbox entry that is due and whose app is
    currently RUNNING. Cheap and safe to call often and from multiple
    triggers: claim_due_outbox_entries atomically claims each row it
    returns, so two overlapping calls to this function split the due rows
    between them instead of racing on the same one.

    app_name scopes the drain to one app (None = every app)."""
    async with db_conn() as conn:
        entries = await db_oidc.claim_due_outbox_entries(conn, app_name=app_name)
    for entry in entries:
        try:
            await _attempt_delivery(entry)
        except Exception as e:
            # Defense in depth: a bug in the bookkeeping above must not stop
            # other entries in this batch from being attempted.
            log.error(
                "unexpected error delivering backchannel logout (client %s, sid %s): %s",
                entry["client_id"],
                entry["sid"],
                e,
            )
    if entries:
        # Delivery outcomes changed the outbox; let the barrier set rebuild.
        await signals.on_backchannel_outbox_update.send_async()


@signals.on_apps_update.connect
async def _drain_on_apps_update(_):
    await drain_due_outbox()
