from datetime import datetime, timezone
from typing import LiteralString

from psycopg import AsyncConnection
from psycopg.rows import dict_row

_UPDATABLE_COLUMNS = {"name", "icon", "last_connection"}

# A device is "paired" while unpaired_at is NULL. Once unpairing sets it,
# the row is kept only until its back-channel logouts are delivered, and must
# be invisible to every paired-device path meanwhile — so there is no
# unfiltered general-purpose getter, only paired-only and unpaired-only
# variants, and a caller cannot forget the filter.


async def list_paired(conn: AsyncConnection) -> list[dict]:
    sql: LiteralString = "SELECT * FROM terminals WHERE unpaired_at IS NULL"
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(sql)
        return await cur.fetchall()


async def get_paired_by_id(conn: AsyncConnection, id: str) -> dict | None:
    sql: LiteralString = "SELECT * FROM terminals WHERE id = %s AND unpaired_at IS NULL"
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(sql, (id,))
        return await cur.fetchone()


async def get_paired_by_name(conn: AsyncConnection, name: str) -> dict | None:
    sql: LiteralString = "SELECT * FROM terminals WHERE name = %s AND unpaired_at IS NULL"
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(sql, (name,))
        return await cur.fetchone()


async def count_paired(conn: AsyncConnection) -> int:
    sql: LiteralString = "SELECT COUNT(*) FROM terminals WHERE unpaired_at IS NULL"
    async with conn.cursor() as cur:
        await cur.execute(sql)
        return (await cur.fetchone())[0]


async def list_unpaired(conn: AsyncConnection) -> list[dict]:
    sql: LiteralString = "SELECT * FROM terminals WHERE unpaired_at IS NOT NULL"
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(sql)
        return await cur.fetchall()


async def get_unpaired_by_id(conn: AsyncConnection, id: str) -> dict | None:
    sql: LiteralString = "SELECT * FROM terminals WHERE id = %s AND unpaired_at IS NOT NULL"
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(sql, (id,))
        return await cur.fetchone()


async def insert(conn: AsyncConnection, terminal: dict) -> dict:
    sql: LiteralString = """INSERT INTO terminals (id, name, icon, last_connection, user_id, paired_at)
        VALUES (%(id)s, %(name)s, %(icon)s, %(last_connection)s, %(user_id)s, %(paired_at)s)
        RETURNING *"""
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(sql, terminal)
        return await cur.fetchone()


async def update_paired(conn: AsyncConnection, id: str, data: dict) -> dict | None:
    set_clauses = []
    params = {"_id": id}
    for key, value in data.items():
        if key not in _UPDATABLE_COLUMNS:
            raise ValueError(f"Invalid column: {key}")
        set_clauses.append(f"{key} = %({key})s")
        params[key] = value
    if not set_clauses:
        return await get_paired_by_id(conn, id)
    sql = (
        f"UPDATE terminals SET {', '.join(set_clauses)} "
        f"WHERE id = %(_id)s AND unpaired_at IS NULL RETURNING *"
    )
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(sql, params)
        return await cur.fetchone()


async def mark_unpaired(conn: AsyncConnection, id: str) -> None:
    """Flag a paired device as unpaired. Final: a flagged row never becomes
    paired again (pairing the same device creates a new terminal)."""
    sql: LiteralString = "UPDATE terminals SET unpaired_at = %s WHERE id = %s AND unpaired_at IS NULL"
    await conn.execute(sql, (datetime.now(timezone.utc), id))


async def remove(conn: AsyncConnection, id: str):
    sql: LiteralString = "DELETE FROM terminals WHERE id = %s"
    await conn.execute(sql, (id,))
