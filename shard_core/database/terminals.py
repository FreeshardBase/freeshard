from typing import LiteralString

from psycopg import AsyncConnection
from psycopg.rows import dict_row

_UPDATABLE_COLUMNS = {"name", "icon", "last_connection"}


async def get_all(conn: AsyncConnection) -> list[dict]:
    sql: LiteralString = "SELECT * FROM terminals"
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(sql)
        return await cur.fetchall()


async def get_by_id(conn: AsyncConnection, id: str) -> dict | None:
    sql: LiteralString = "SELECT * FROM terminals WHERE id = %s"
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(sql, (id,))
        return await cur.fetchone()


async def get_by_name(conn: AsyncConnection, name: str) -> dict | None:
    sql: LiteralString = "SELECT * FROM terminals WHERE name = %s"
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(sql, (name,))
        return await cur.fetchone()


async def insert(conn: AsyncConnection, terminal: dict) -> dict:
    sql: LiteralString = """INSERT INTO terminals (id, name, icon, last_connection)
        VALUES (%(id)s, %(name)s, %(icon)s, %(last_connection)s)
        RETURNING *"""
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(sql, terminal)
        return await cur.fetchone()


async def update(conn: AsyncConnection, id: str, data: dict) -> dict | None:
    set_clauses = []
    params = {"_id": id}
    for key, value in data.items():
        if key not in _UPDATABLE_COLUMNS:
            raise ValueError(f"Invalid column: {key}")
        set_clauses.append(f"{key} = %({key})s")
        params[key] = value
    if not set_clauses:
        return await get_by_id(conn, id)
    sql = (
        f"UPDATE terminals SET {', '.join(set_clauses)} WHERE id = %(_id)s RETURNING *"
    )
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(sql, params)
        return await cur.fetchone()


async def remove(conn: AsyncConnection, id: str):
    sql: LiteralString = "DELETE FROM terminals WHERE id = %s"
    await conn.execute(sql, (id,))


async def count(conn: AsyncConnection) -> int:
    sql: LiteralString = "SELECT COUNT(*) FROM terminals"
    async with conn.cursor() as cur:
        await cur.execute(sql)
        return (await cur.fetchone())[0]
