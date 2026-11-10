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
such reconciliation; the next drain just picks it up again. Delivery itself
(minting the token, POSTing it, retrying, draining on app RUNNING) lands in a
follow-up commit on this same branch — see git log for this file.
"""

from shard_core.database import oidc as db_oidc


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
