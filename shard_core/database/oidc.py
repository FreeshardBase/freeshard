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
        await cur.execute(
            sql, {**client, "redirect_uris": Jsonb(client["redirect_uris"])}
        )
        return await cur.fetchone()


async def get_client(conn: AsyncConnection, client_id: str) -> OidcClient | None:
    sql: LiteralString = "SELECT * FROM oidc_clients WHERE client_id = %s"
    async with conn.cursor(row_factory=class_row(OidcClient)) as cur:
        await cur.execute(sql, (client_id,))
        return await cur.fetchone()


async def get_client_by_app_name(
    conn: AsyncConnection, app_name: str
) -> OidcClient | None:
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


async def redeem_code(
    conn: AsyncConnection, code_hash: str, client_id: str
) -> OidcCode | None:
    """Atomically consume the code — the single UPDATE makes concurrent
    redemptions of the same code impossible (only one caller gets the row)."""
    sql: LiteralString = """UPDATE oidc_codes SET redeemed = TRUE
        WHERE code_hash = %s AND client_id = %s AND NOT redeemed AND expires_at > now()
        RETURNING *"""
    async with conn.cursor(row_factory=class_row(OidcCode)) as cur:
        await cur.execute(sql, (code_hash, client_id))
        return await cur.fetchone()


async def get_code(
    conn: AsyncConnection, code_hash: str, client_id: str
) -> OidcCode | None:
    sql: LiteralString = (
        "SELECT * FROM oidc_codes WHERE code_hash = %s AND client_id = %s"
    )
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


async def get_token_by_access_hash(
    conn: AsyncConnection, access_token_hash: str
) -> OidcToken | None:
    sql: LiteralString = (
        "SELECT * FROM oidc_tokens WHERE access_token_hash = %s AND NOT revoked"
    )
    async with conn.cursor(row_factory=class_row(OidcToken)) as cur:
        await cur.execute(sql, (access_token_hash,))
        return await cur.fetchone()


async def get_token_by_refresh_hash(
    conn: AsyncConnection, refresh_token_hash: str
) -> OidcToken | None:
    # revoked rows included on purpose — rotated-token replay must be
    # distinguishable from an unknown token (reuse detection)
    sql: LiteralString = "SELECT * FROM oidc_tokens WHERE refresh_token_hash = %s"
    async with conn.cursor(row_factory=class_row(OidcToken)) as cur:
        await cur.execute(sql, (refresh_token_hash,))
        return await cur.fetchone()


async def revoke_token(conn: AsyncConnection, access_token_hash: str):
    sql: LiteralString = (
        "UPDATE oidc_tokens SET revoked = TRUE WHERE access_token_hash = %s"
    )
    await conn.execute(sql, (access_token_hash,))


async def revoke_all_for_grant(conn: AsyncConnection, client_id: str, user_sub: int):
    sql: LiteralString = (
        "UPDATE oidc_tokens SET revoked = TRUE WHERE client_id = %s AND user_sub = %s"
    )
    await conn.execute(sql, (client_id, user_sub))


async def revoke_for_terminal(conn: AsyncConnection, terminal_id: str):
    """Kill everything issued to one device, on un-pair.

    Must run before the terminals row is deleted — the FK is ON DELETE SET NULL,
    so afterwards nothing matches terminal_id any more.
    """
    revoke_tokens: LiteralString = (
        "UPDATE oidc_tokens SET revoked = TRUE WHERE terminal_id = %s"
    )
    burn_codes: LiteralString = (
        "UPDATE oidc_codes SET redeemed = TRUE WHERE terminal_id = %s AND NOT redeemed"
    )
    await conn.execute(revoke_tokens, (terminal_id,))
    await conn.execute(burn_codes, (terminal_id,))


# --- backchannel logout outbox ----------------------------------------------


async def get_live_grants_for_terminal(
    conn: AsyncConnection, terminal_id: str
) -> list[dict]:
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


async def enqueue_backchannel_logout(
    conn: AsyncConnection, terminal_id: str, grants: list[dict]
) -> None:
    """One outbox row per (client_id, sid) grant whose client declared a
    backchannel_logout_uri — nothing to deliver to otherwise. Idempotent: a
    (client_id, sid) pair already enqueued is left alone (ON CONFLICT DO
    NOTHING), so calling this twice for the same grant is harmless."""
    sql: LiteralString = """INSERT INTO oidc_backchannel_logout_outbox
        (client_id, user_sub, sid, terminal_id)
        SELECT %(client_id)s, %(user_sub)s, %(sid)s, %(terminal_id)s
        WHERE EXISTS (
            SELECT 1 FROM oidc_clients
            WHERE client_id = %(client_id)s AND backchannel_logout_uri IS NOT NULL
        )
        ON CONFLICT (client_id, sid) DO NOTHING"""
    for grant in grants:
        await conn.execute(sql, {**grant, "terminal_id": terminal_id})


async def claim_due_outbox_entries(
    conn: AsyncConnection, stuck_after_seconds: int = 120
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
    failed) is reclaimed the same way — otherwise a single crash would strand
    the row forever, no different in kind from the installation worker's own
    in-memory-queue hazard this outbox exists to avoid.
    """
    claim_sql: LiteralString = """UPDATE oidc_backchannel_logout_outbox
        SET status = 'in_flight', updated = now()
        WHERE id IN (
            SELECT o.id
            FROM oidc_backchannel_logout_outbox o
            JOIN oidc_clients c ON c.client_id = o.client_id
            JOIN installed_apps ia ON ia.name = c.app_name
            WHERE ia.status = 'running'
              AND (
                (o.status = 'pending' AND o.next_attempt_at <= now())
                OR (o.status = 'in_flight'
                    AND o.updated <= now() - %(stuck_after)s * INTERVAL '1 second')
              )
            FOR UPDATE OF o SKIP LOCKED
        )
        RETURNING id"""
    async with conn.cursor() as cur:
        await cur.execute(claim_sql, {"stuck_after": stuck_after_seconds})
        claimed_ids = [row[0] for row in await cur.fetchall()]
    if not claimed_ids:
        return []
    fetch_sql: LiteralString = """SELECT o.*, c.backchannel_logout_uri, c.app_name
        FROM oidc_backchannel_logout_outbox o
        JOIN oidc_clients c ON c.client_id = o.client_id
        WHERE o.id = ANY(%s)"""
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(fetch_sql, (claimed_ids,))
        return await cur.fetchall()


async def mark_outbox_delivered(conn: AsyncConnection, id_: int) -> None:
    sql: LiteralString = """UPDATE oidc_backchannel_logout_outbox
        SET status = 'delivered', updated = now() WHERE id = %s"""
    await conn.execute(sql, (id_,))


async def mark_outbox_retry(
    conn: AsyncConnection,
    id_: int,
    attempts: int,
    next_attempt_at: datetime,
    error: str,
) -> None:
    """Release the claim: back to 'pending' so the next due drain can pick
    it up again (it would otherwise stay 'in_flight' forever)."""
    sql: LiteralString = """UPDATE oidc_backchannel_logout_outbox
        SET status = 'pending', attempts = %s, next_attempt_at = %s,
            last_error = %s, updated = now()
        WHERE id = %s"""
    await conn.execute(sql, (attempts, next_attempt_at, error, id_))


async def mark_outbox_failed(
    conn: AsyncConnection, id_: int, attempts: int, error: str
) -> None:
    sql: LiteralString = """UPDATE oidc_backchannel_logout_outbox
        SET status = 'failed', attempts = %s, last_error = %s, updated = now()
        WHERE id = %s"""
    await conn.execute(sql, (attempts, error, id_))


async def get_outbox_entries_by_status(
    conn: AsyncConnection, status: str
) -> list[dict]:
    """Queryable durable state for a future "delivery failed for this
    terminal/client" UI marker — deliberately not built here (see issue #192:
    that's a separate Sundial-repo follow-up). This is the backend half it
    will read from."""
    sql: LiteralString = """SELECT o.*, c.app_name
        FROM oidc_backchannel_logout_outbox o
        JOIN oidc_clients c ON c.client_id = o.client_id
        WHERE o.status = %s"""
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(sql, (status,))
        return await cur.fetchall()
