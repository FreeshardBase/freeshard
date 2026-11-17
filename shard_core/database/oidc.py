from datetime import datetime
from typing import LiteralString

from psycopg import AsyncConnection
from psycopg.rows import class_row, dict_row
from psycopg.types.json import Jsonb

from shard_core.data_model.oidc import OidcClient, OidcCode, OidcToken

# --- clients ---------------------------------------------------------------


async def upsert_client(conn: AsyncConnection, client: dict) -> OidcClient:
    """Insert the client, or refresh its configuration if the app already has
    one — existing client_id/client_secret are preserved so reinstalls and
    re-renders keep working credentials."""
    sql: LiteralString = """INSERT INTO oidc_clients
        (client_id, client_secret, app_name, redirect_uris,
         scope, token_endpoint_auth_method, backchannel_logout_uri)
        VALUES (%(client_id)s, %(client_secret)s, %(app_name)s, %(redirect_uris)s,
                %(scope)s, %(token_endpoint_auth_method)s, %(backchannel_logout_uri)s)
        ON CONFLICT (app_name) DO UPDATE SET
            redirect_uris = EXCLUDED.redirect_uris,
            scope = EXCLUDED.scope,
            token_endpoint_auth_method = EXCLUDED.token_endpoint_auth_method,
            backchannel_logout_uri = EXCLUDED.backchannel_logout_uri
        RETURNING *"""
    async with conn.cursor(row_factory=class_row(OidcClient)) as cur:
        await cur.execute(sql, {**client, "redirect_uris": Jsonb(client["redirect_uris"])})
        return await cur.fetchone()


async def get_client(conn: AsyncConnection, client_id: str) -> OidcClient | None:
    sql: LiteralString = "SELECT * FROM oidc_clients WHERE client_id = %s"
    async with conn.cursor(row_factory=class_row(OidcClient)) as cur:
        await cur.execute(sql, (client_id,))
        return await cur.fetchone()


async def get_client_by_app_name(conn: AsyncConnection, app_name: str) -> OidcClient | None:
    sql: LiteralString = "SELECT * FROM oidc_clients WHERE app_name = %s"
    async with conn.cursor(row_factory=class_row(OidcClient)) as cur:
        await cur.execute(sql, (app_name,))
        return await cur.fetchone()


# --- authorization codes ------------------------------------------------------


async def insert_code(conn: AsyncConnection, code: dict):
    sql: LiteralString = """INSERT INTO oidc_codes
        (code_hash, client_id, redirect_uri, scope, user_sub, terminal_id, sid, nonce,
         code_challenge, code_challenge_method, auth_time, expires_at)
        VALUES (%(code_hash)s, %(client_id)s, %(redirect_uri)s, %(scope)s, %(user_sub)s,
                %(terminal_id)s, %(sid)s,
                %(nonce)s, %(code_challenge)s, %(code_challenge_method)s,
                %(auth_time)s, %(expires_at)s)"""
    await conn.execute(sql, code)


async def redeem_code(conn: AsyncConnection, code_hash: str, client_id: str) -> OidcCode | None:
    """Atomically consume the code — the single UPDATE makes concurrent
    redemptions of the same code impossible (only one caller gets the row)."""
    sql: LiteralString = """UPDATE oidc_codes SET redeemed = TRUE
        WHERE code_hash = %s AND client_id = %s AND NOT redeemed AND expires_at > now()
        RETURNING *"""
    async with conn.cursor(row_factory=class_row(OidcCode)) as cur:
        await cur.execute(sql, (code_hash, client_id))
        return await cur.fetchone()


async def get_code(conn: AsyncConnection, code_hash: str, client_id: str) -> OidcCode | None:
    sql: LiteralString = "SELECT * FROM oidc_codes WHERE code_hash = %s AND client_id = %s"
    async with conn.cursor(row_factory=class_row(OidcCode)) as cur:
        await cur.execute(sql, (code_hash, client_id))
        return await cur.fetchone()


async def exists_nonce(conn: AsyncConnection, nonce: str, client_id: str) -> bool:
    sql: LiteralString = "SELECT 1 FROM oidc_codes WHERE nonce = %s AND client_id = %s"
    async with conn.cursor() as cur:
        await cur.execute(sql, (nonce, client_id))
        return await cur.fetchone() is not None


# --- tokens --------------------------------------------------------------------


async def insert_token(conn: AsyncConnection, token: dict):
    sql: LiteralString = """INSERT INTO oidc_tokens
        (access_token_hash, refresh_token_hash, client_id, user_sub, terminal_id, sid,
         scope, issued_at, expires_in)
        VALUES (%(access_token_hash)s, %(refresh_token_hash)s, %(client_id)s, %(user_sub)s,
                %(terminal_id)s, %(sid)s,
                %(scope)s, %(issued_at)s, %(expires_in)s)"""
    await conn.execute(sql, token)


async def get_token_by_access_hash(conn: AsyncConnection, access_token_hash: str) -> OidcToken | None:
    sql: LiteralString = "SELECT * FROM oidc_tokens WHERE access_token_hash = %s AND NOT revoked"
    async with conn.cursor(row_factory=class_row(OidcToken)) as cur:
        await cur.execute(sql, (access_token_hash,))
        return await cur.fetchone()


async def get_token_by_refresh_hash(conn: AsyncConnection, refresh_token_hash: str) -> OidcToken | None:
    # revoked rows included on purpose — rotated-token replay must be
    # distinguishable from an unknown token (reuse detection)
    sql: LiteralString = "SELECT * FROM oidc_tokens WHERE refresh_token_hash = %s"
    async with conn.cursor(row_factory=class_row(OidcToken)) as cur:
        await cur.execute(sql, (refresh_token_hash,))
        return await cur.fetchone()


async def revoke_token(conn: AsyncConnection, access_token_hash: str):
    sql: LiteralString = "UPDATE oidc_tokens SET revoked = TRUE WHERE access_token_hash = %s"
    await conn.execute(sql, (access_token_hash,))


async def revoke_all_for_grant(conn: AsyncConnection, client_id: str, user_sub: int):
    sql: LiteralString = "UPDATE oidc_tokens SET revoked = TRUE WHERE client_id = %s AND user_sub = %s"
    await conn.execute(sql, (client_id, user_sub))


async def revoke_for_terminal(conn: AsyncConnection, terminal_id: str):
    """Kill everything issued to one device, on un-pair.

    Must run before the terminals row is deleted — the FK is ON DELETE SET NULL,
    so afterwards nothing matches terminal_id any more.
    """
    revoke_tokens: LiteralString = "UPDATE oidc_tokens SET revoked = TRUE WHERE terminal_id = %s"
    burn_codes: LiteralString = "UPDATE oidc_codes SET redeemed = TRUE WHERE terminal_id = %s AND NOT redeemed"
    await conn.execute(revoke_tokens, (terminal_id,))
    await conn.execute(burn_codes, (terminal_id,))


# --- backchannel logout outbox ----------------------------------------------


async def get_live_grants_for_terminal(conn: AsyncConnection, terminal_id: str) -> list[dict]:
    """Distinct (client, sid, user) combinations with a live (unrevoked)
    token for this terminal — the app sessions a back-channel logout must
    notify. Must be called before revoke_for_terminal marks these tokens
    revoked, and before the terminal row is deleted (the FK is ON DELETE SET
    NULL, so afterwards nothing matches terminal_id any more)."""
    sql: LiteralString = """SELECT DISTINCT client_id, sid, user_sub
        FROM oidc_tokens WHERE terminal_id = %s AND NOT revoked"""
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(sql, (terminal_id,))
        return await cur.fetchall()


async def enqueue_backchannel_logout(conn: AsyncConnection, terminal_id: str, grants: list[dict]) -> int:
    """One outbox row per (app_name, sid) grant whose client declared a
    backchannel_logout_uri — nothing to deliver to otherwise. The app is
    resolved by name from the client at enqueue time and stored as app_name,
    so the row survives the client being dropped on uninstall. Idempotent: an
    (app_name, sid) pair already enqueued is left alone (ON CONFLICT DO
    NOTHING). Returns the number of rows actually enqueued."""
    sql: LiteralString = """INSERT INTO oidc_backchannel_logout_outbox
        (app_name, user_sub, sid, terminal_id)
        SELECT c.app_name, %(user_sub)s, %(sid)s, %(terminal_id)s
        FROM oidc_clients c
        WHERE c.client_id = %(client_id)s AND c.backchannel_logout_uri IS NOT NULL
        ON CONFLICT (app_name, sid) DO NOTHING"""
    enqueued = 0
    for grant in grants:
        cur = await conn.execute(sql, {**grant, "terminal_id": terminal_id})
        enqueued += cur.rowcount
    return enqueued


async def claim_due_outbox_entries(
    conn: AsyncConnection, stuck_after_seconds: int = 120, app_name: str | None = None
) -> list[dict]:
    """Atomically claim pending outbox rows whose backoff has elapsed and
    whose app is currently RUNNING — flipping them to 'in_flight' in the same
    statement that selects them.

    drain_due_outbox() has two independent, uncoordinated callers (the
    on_apps_update signal and a periodic backstop), so two overlapping drains
    are routine, not an edge case. A bare SELECT here would let both fetch the
    same row and both attempt delivery: duplicate logout_token POSTs to the
    relying party, and a lost-update on `attempts` (two racing
    mark_outbox_retry calls each computing the same "+1" from a stale
    snapshot), letting a row dodge MAX_ATTEMPTS far longer than intended.
    `WHERE id IN (SELECT ... FOR UPDATE SKIP LOCKED)` makes two concurrent
    claims disjoint instead of racing: whichever transaction's SELECT commits
    the row-lock first wins it, and SKIP LOCKED makes the other claim simply
    not see it, rather than block or double-claim.

    A row stuck 'in_flight' longer than stuck_after_seconds (the process
    crashed between claiming it and calling mark_outbox_delivered/retry/
    failed) is reclaimed the same way — otherwise a single crash would
    strand the row forever.

    app_name scopes the claim to a single app when given (NULL = every app).
    """
    claim_sql: LiteralString = """UPDATE oidc_backchannel_logout_outbox
        SET status = 'in_flight', updated = now()
        WHERE id IN (
            SELECT o.id
            FROM oidc_backchannel_logout_outbox o
            JOIN installed_apps ia ON ia.name = o.app_name
            WHERE ia.status = 'running'
              AND (%(app_name)s::text IS NULL OR o.app_name = %(app_name)s)
              AND (
                (o.status = 'pending' AND o.next_attempt_at <= now())
                OR (o.status = 'in_flight'
                    AND o.updated <= now() - %(stuck_after)s * INTERVAL '1 second')
              )
            FOR UPDATE OF o SKIP LOCKED
        )
        RETURNING id"""
    async with conn.cursor() as cur:
        await cur.execute(claim_sql, {"stuck_after": stuck_after_seconds, "app_name": app_name})
        claimed_ids = [row[0] for row in await cur.fetchall()]
    if not claimed_ids:
        return []
    # client_id/backchannel_logout_uri come from the app's CURRENT client, not
    # the one that existed at enqueue time: a reinstall registers a new
    # client_id, and the logout token must be signed for whatever client the
    # app has now. LEFT JOIN so a row whose app lost its client still returns
    # (client_id NULL), to be failed by _attempt_delivery rather than dropped.
    fetch_sql: LiteralString = """SELECT o.*, c.client_id, c.backchannel_logout_uri
        FROM oidc_backchannel_logout_outbox o
        LEFT JOIN oidc_clients c ON c.app_name = o.app_name
        WHERE o.id = ANY(%s)"""
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(fetch_sql, (claimed_ids,))
        return await cur.fetchall()


async def mark_outbox_delivered(conn: AsyncConnection, id_: int) -> None:
    """Guarded by `AND status = 'in_flight'`: the claim (claim_due_outbox_
    entries) is what's supposed to make this id_ exclusively ours, but the
    stuck-row reclaim branch of that same query means a row claimed by a
    worker that stalled (slow, not actually crashed) past stuck_after_seconds
    can be re-claimed by a second worker while the first is still running.
    Without this guard, whichever of the two writes last would stomp the
    other's outcome -- a 'delivered' overwritten back to 'pending'/'failed',
    or a lost-update on `attempts`. The guard makes the second writer's
    UPDATE match zero rows instead."""
    sql: LiteralString = """UPDATE oidc_backchannel_logout_outbox
        SET status = 'delivered', updated = now()
        WHERE id = %s AND status = 'in_flight'"""
    await conn.execute(sql, (id_,))


async def mark_outbox_retry(
    conn: AsyncConnection,
    id_: int,
    attempts: int,
    next_attempt_at: datetime,
    error: str,
) -> None:
    """Release the claim: back to 'pending' so the next due drain can pick
    it up again (it would otherwise stay 'in_flight' forever). Guarded by
    `AND status = 'in_flight'` -- see mark_outbox_delivered's docstring."""
    sql: LiteralString = """UPDATE oidc_backchannel_logout_outbox
        SET status = 'pending', attempts = %s, next_attempt_at = %s,
            last_error = %s, updated = now()
        WHERE id = %s AND status = 'in_flight'"""
    await conn.execute(sql, (attempts, next_attempt_at, error, id_))


async def mark_outbox_failed(conn: AsyncConnection, id_: int, attempts: int, error: str) -> None:
    """Guarded by `AND status = 'in_flight'` -- see mark_outbox_delivered's
    docstring."""
    sql: LiteralString = """UPDATE oidc_backchannel_logout_outbox
        SET status = 'failed', attempts = %s, last_error = %s, updated = now()
        WHERE id = %s AND status = 'in_flight'"""
    await conn.execute(sql, (attempts, error, id_))


async def get_apps_with_pending_backchannel_logout(conn: AsyncConnection) -> list[str]:
    """App names that still owe a back-channel logout — a row in the outbox
    not yet delivered or failed ('pending' or 'in_flight'). Read from app_name
    on the outbox, not via a join to oidc_clients, so it is correct while the
    app is uninstalled. Rebuilds the in-process barrier set; see
    service/oidc_backchannel_barrier.py."""
    sql: LiteralString = """SELECT DISTINCT app_name
        FROM oidc_backchannel_logout_outbox
        WHERE status IN ('pending', 'in_flight')"""
    async with conn.cursor() as cur:
        await cur.execute(sql)
        return [row[0] for row in await cur.fetchall()]


async def get_outbox_entries_by_status(conn: AsyncConnection, status: str) -> list[dict]:
    """Outbox rows filtered by delivery status."""
    sql: LiteralString = """SELECT * FROM oidc_backchannel_logout_outbox WHERE status = %s"""
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(sql, (status,))
        return await cur.fetchall()


async def get_undelivered_outbox_with_app_status(conn: AsyncConnection) -> list[dict]:
    """Every outbox row not yet delivered, with its owning app's install
    status (app_status NULL when the app is not installed). The input the
    per-app lockout state is derived from; see service/terminal_lockouts.py."""
    sql: LiteralString = """SELECT o.id, o.terminal_id, o.app_name, o.status, ia.status AS app_status
        FROM oidc_backchannel_logout_outbox o
        LEFT JOIN installed_apps ia ON ia.name = o.app_name
        WHERE o.status IN ('pending', 'in_flight', 'failed')"""
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(sql)
        return await cur.fetchall()


async def reset_failed_outbox_for_terminal(conn: AsyncConnection, terminal_id: str) -> int:
    """Reset a device's exhausted ('failed') lockouts back to pending, due now,
    so a drain retries them. Returns the number of rows reset."""
    sql: LiteralString = """UPDATE oidc_backchannel_logout_outbox
        SET status = 'pending', attempts = 0, next_attempt_at = now(),
            last_error = NULL, updated = now()
        WHERE terminal_id = %s AND status = 'failed'"""
    cur = await conn.execute(sql, (terminal_id,))
    return cur.rowcount


async def reap_fully_delivered_unpaired_terminals(conn: AsyncConnection) -> list[str]:
    """Delete every unpaired device whose lockouts are all delivered (no
    pending/in_flight/failed row left). The cascade on terminal_id removes the
    delivered rows with it, so delivered rows never accumulate. Returns the
    deleted terminal ids."""
    sql: LiteralString = """DELETE FROM terminals t
        WHERE t.unpaired_at IS NOT NULL
          AND NOT EXISTS (
            SELECT 1 FROM oidc_backchannel_logout_outbox o
            WHERE o.terminal_id = t.id AND o.status <> 'delivered'
          )
        RETURNING t.id"""
    async with conn.cursor() as cur:
        await cur.execute(sql)
        return [row[0] for row in await cur.fetchall()]
