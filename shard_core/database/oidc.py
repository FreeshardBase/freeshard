from typing import LiteralString

from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

# --- clients ---------------------------------------------------------------


async def upsert_client(conn: AsyncConnection, client: dict) -> dict:
    sql: LiteralString = """INSERT INTO oidc_clients
        (client_id, client_secret, app_name, redirect_uris, scope, token_endpoint_auth_method)
        VALUES (%(client_id)s, %(client_secret)s, %(app_name)s, %(redirect_uris)s,
                %(scope)s, %(token_endpoint_auth_method)s)
        ON CONFLICT (app_name) DO UPDATE SET
            client_id = EXCLUDED.client_id,
            client_secret = EXCLUDED.client_secret,
            redirect_uris = EXCLUDED.redirect_uris,
            scope = EXCLUDED.scope,
            token_endpoint_auth_method = EXCLUDED.token_endpoint_auth_method
        RETURNING *"""
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            sql, {**client, "redirect_uris": Jsonb(client["redirect_uris"])}
        )
        return await cur.fetchone()


async def get_client(conn: AsyncConnection, client_id: str) -> dict | None:
    sql: LiteralString = "SELECT * FROM oidc_clients WHERE client_id = %s"
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(sql, (client_id,))
        return await cur.fetchone()


# --- authorization codes ------------------------------------------------------


async def insert_code(conn: AsyncConnection, code: dict):
    sql: LiteralString = """INSERT INTO oidc_codes
        (code_hash, client_id, redirect_uri, scope, user_sub, nonce,
         code_challenge, code_challenge_method, auth_time, expires_at)
        VALUES (%(code_hash)s, %(client_id)s, %(redirect_uri)s, %(scope)s, %(user_sub)s,
                %(nonce)s, %(code_challenge)s, %(code_challenge_method)s,
                %(auth_time)s, %(expires_at)s)"""
    await conn.execute(sql, code)


async def redeem_code(
    conn: AsyncConnection, code_hash: str, client_id: str
) -> dict | None:
    """Atomically consume the code — the single UPDATE makes concurrent
    redemptions of the same code impossible (only one caller gets the row)."""
    sql: LiteralString = """UPDATE oidc_codes SET redeemed = TRUE
        WHERE code_hash = %s AND client_id = %s AND NOT redeemed AND expires_at > now()
        RETURNING *"""
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(sql, (code_hash, client_id))
        return await cur.fetchone()


async def get_code(
    conn: AsyncConnection, code_hash: str, client_id: str
) -> dict | None:
    sql: LiteralString = (
        "SELECT * FROM oidc_codes WHERE code_hash = %s AND client_id = %s"
    )
    async with conn.cursor(row_factory=dict_row) as cur:
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
        (access_token_hash, refresh_token_hash, client_id, user_sub, scope, issued_at, expires_in)
        VALUES (%(access_token_hash)s, %(refresh_token_hash)s, %(client_id)s, %(user_sub)s,
                %(scope)s, %(issued_at)s, %(expires_in)s)"""
    await conn.execute(sql, token)


async def get_token_by_access_hash(
    conn: AsyncConnection, access_token_hash: str
) -> dict | None:
    sql: LiteralString = (
        "SELECT * FROM oidc_tokens WHERE access_token_hash = %s AND NOT revoked"
    )
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(sql, (access_token_hash,))
        return await cur.fetchone()


async def get_token_by_refresh_hash(
    conn: AsyncConnection, refresh_token_hash: str
) -> dict | None:
    # revoked rows included on purpose — rotated-token replay must be
    # distinguishable from an unknown token (reuse detection)
    sql: LiteralString = "SELECT * FROM oidc_tokens WHERE refresh_token_hash = %s"
    async with conn.cursor(row_factory=dict_row) as cur:
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
