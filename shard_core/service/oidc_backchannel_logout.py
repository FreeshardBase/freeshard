"""Delivery of OIDC Back-Channel Logout 1.0 notifications to installed apps.

Follow-up to the terminal-binding work (issue #189): that revoked everything
the shard itself issued on un-pair (oidc.revoke_for_terminal), but a relying
party like Immich mints its own app-local session at the OAuth callback and
never re-checks the IdP, so a revoked access token changes nothing for a
browser or phone that is already logged in. This module closes that gap by
pushing a logout_token to the app, per OIDC Back-Channel Logout 1.0.

Enqueue happens synchronously inside the un-pair transaction
(web/protected/terminals.py, see enqueue_for_terminal): the terminal's live
(unrevoked) OIDC grants are read and one outbox row is written per
(client_id, sid) that has somewhere to go, BEFORE oidc.revoke_for_terminal
marks those grants revoked and before the terminals row disappears (its FK is
ON DELETE SET NULL — the linkage is gone afterwards).

Delivery is out-of-band and durable: migration shard-core-0008 gives the
outbox a table, not an in-memory queue — see the installation worker's
analogous in-memory-queue hazard (service/app_installation/worker.py) and the
reconcile_interrupted_* steps it needed to compensate. An outbox row needs no
such reconciliation; the next drain just picks it up again.

drain_due_outbox() attempts delivery of every outbox entry that is due and
whose owning app is currently RUNNING (get_due_outbox_entries bakes that
filter in — a stopped app is never woken just to receive its own logout).
Wiring drain_due_outbox() to actually run (the on_apps_update signal, plus a
periodic backstop for retries) lands in a follow-up commit on this branch.

The logout_token is minted fresh on every delivery attempt
(oidc_provider.sign_logout_token), never cached from enqueue time: Immich
validates it with maxTokenAge: '2m' (server/src/repositories/
oauth.repository.ts), so a token signed at un-pair and retried minutes later
would be rejected by the relying party even though delivery itself went
through. This is the single most likely implementation bug in this feature —
see tests/test_oidc_backchannel_logout.py for a regression test that retries
after a simulated delay and asserts the second token is not the first.
"""

import logging
from datetime import datetime, timedelta, timezone

import httpx

from shard_core.database import oidc as db_oidc
from shard_core.database.connection import db_conn
from shard_core.service import oidc_provider

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
    """The actual network call, factored out so tests can patch exactly this
    (same pattern as app_installation.worker._download_app_zip) instead of
    mocking the httpx client machinery."""
    async with httpx.AsyncClient(timeout=DELIVERY_TIMEOUT) as client:
        response = await client.post(url, data={"logout_token": token})
    response.raise_for_status()


async def _attempt_delivery(entry: dict) -> None:
    await oidc_provider.ensure_configured()
    token = oidc_provider.sign_logout_token(
        client_id=entry["client_id"], user_sub=entry["user_sub"], sid=entry["sid"]
    )
    error = None
    try:
        await _post_logout_token(entry["backchannel_logout_uri"], token)
    except httpx.HTTPError as e:
        error = f"{type(e).__name__}: {e}"

    async with db_conn() as conn:
        if error is None:
            await db_oidc.mark_outbox_delivered(conn, entry["id"])
            return
        attempts = entry["attempts"] + 1
        if attempts >= MAX_ATTEMPTS:
            log.error(
                "backchannel logout delivery to app %s (client %s, sid %s) "
                "failed permanently after %d attempts: %s",
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
                "backchannel logout delivery to app %s (client %s, sid %s) "
                "failed (attempt %d/%d), retrying in %ds: %s",
                entry["app_name"],
                entry["client_id"],
                entry["sid"],
                attempts,
                MAX_ATTEMPTS,
                delay,
                error,
            )
            await db_oidc.mark_outbox_retry(
                conn, entry["id"], attempts, next_attempt_at, error
            )


async def drain_due_outbox() -> None:
    """Attempt delivery of every outbox entry that is due and whose app is
    currently RUNNING. Cheap and safe to call often and from multiple
    triggers: each entry is independent, and a delivered/failed row simply
    stops matching the WHERE clause on the next call."""
    async with db_conn() as conn:
        entries = await db_oidc.get_due_outbox_entries(conn)
    for entry in entries:
        try:
            await _attempt_delivery(entry)
        except Exception as e:
            # Defense in depth: a bug in the bookkeeping above must not stop
            # other entries in this batch from being attempted.
            log.error(
                "unexpected error delivering backchannel logout "
                "(client %s, sid %s): %s",
                entry["client_id"],
                entry["sid"],
                e,
            )
