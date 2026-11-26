from typing import LiteralString

from psycopg import AsyncConnection
from psycopg.rows import class_row

from shard_core.data_model.user import User

_UPDATABLE_COLUMNS = {
    "username",
    "display_name",
    "email",
    "pending_email",
    "email_token_hash",
    "email_token_expires",
    "role",
    "disabled",
}


async def get_by_id(conn: AsyncConnection, id: int) -> User | None:
    sql: LiteralString = "SELECT * FROM users WHERE id = %s"
    async with conn.cursor(row_factory=class_row(User)) as cur:
        await cur.execute(sql, (id,))
        return await cur.fetchone()


async def get_owner(conn: AsyncConnection) -> User | None:
    sql: LiteralString = "SELECT * FROM users WHERE role = 'owner'"
    async with conn.cursor(row_factory=class_row(User)) as cur:
        await cur.execute(sql)
        return await cur.fetchone()


async def insert(conn: AsyncConnection, user: dict) -> User:
    sql: LiteralString = """INSERT INTO users (username, display_name, email, role)
        VALUES (%(username)s, %(display_name)s, %(email)s, %(role)s)
        RETURNING *"""
    async with conn.cursor(row_factory=class_row(User)) as cur:
        await cur.execute(sql, user)
        return await cur.fetchone()


async def update(conn: AsyncConnection, id: int, data: dict) -> User | None:
    set_clauses = []
    params = {"_id": id}
    for key, value in data.items():
        if key not in _UPDATABLE_COLUMNS:
            raise ValueError(f"Invalid column: {key}")
        set_clauses.append(f"{key} = %({key})s")
        params[key] = value
    if not set_clauses:
        return await get_by_id(conn, id)
    sql = f"UPDATE users SET {', '.join(set_clauses)} WHERE id = %(_id)s RETURNING *"
    async with conn.cursor(row_factory=class_row(User)) as cur:
        await cur.execute(sql, params)
        return await cur.fetchone()


async def get_all_with_pending_email_token(conn: AsyncConnection) -> list[User]:
    """Every user holding a confirmation token, so the caller can match the
    digest with secrets.compare_digest rather than inside an index."""
    sql: LiteralString = "SELECT * FROM users WHERE email_token_hash IS NOT NULL"
    async with conn.cursor(row_factory=class_row(User)) as cur:
        await cur.execute(sql)
        return await cur.fetchall()


async def claim_email_token(conn: AsyncConnection, id: int, token_hash: str):
    """Spend the confirmation token, returning the row it was spent on.

    The token is cleared and the candidate read in one statement, so a
    double-submitted link promotes once: the second call matches nothing.
    Returns None when the token is gone, expired, or has no candidate left.
    The returned row still carries the pending_email to promote.
    """
    sql: LiteralString = """UPDATE users
        SET email_token_hash = NULL, email_token_expires = NULL
        WHERE id = %s
          AND email_token_hash = %s
          AND email_token_expires > now()
          AND pending_email IS NOT NULL
        RETURNING *"""
    async with conn.cursor(row_factory=class_row(User)) as cur:
        await cur.execute(sql, (id, token_hash))
        return await cur.fetchone()


async def promote_pending_email(conn: AsyncConnection, id: int, address: str):
    """Make *address* the verified address, unless the candidate moved on.

    Guarded on pending_email so a candidate set while this confirmation was in
    flight survives instead of being cleared by it.
    """
    sql: LiteralString = """UPDATE users SET email = %(address)s, pending_email = NULL
        WHERE id = %(id)s AND pending_email = %(address)s
        RETURNING *"""
    async with conn.cursor(row_factory=class_row(User)) as cur:
        await cur.execute(sql, {"id": id, "address": address})
        return await cur.fetchone()


async def count(conn: AsyncConnection) -> int:
    sql: LiteralString = "SELECT COUNT(*) FROM users"
    async with conn.cursor() as cur:
        await cur.execute(sql)
        return (await cur.fetchone())[0]
