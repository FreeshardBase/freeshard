import logging
from typing import Optional

from psycopg import AsyncConnection
from psycopg.rows import dict_row

log = logging.getLogger(__name__)


async def get_all(conn: AsyncConnection) -> list[dict]:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute("SELECT * FROM terminals")
        return await cur.fetchall()


async def get_by_id(conn: AsyncConnection, id: str) -> Optional[dict]:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute("SELECT * FROM terminals WHERE id = %(id)s", {"id": id})
        return await cur.fetchone()


async def get_by_name(conn: AsyncConnection, name: str) -> Optional[dict]:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT * FROM terminals WHERE name = %(name)s", {"name": name}
        )
        return await cur.fetchone()


async def insert(conn: AsyncConnection, terminal: dict):
    async with conn.cursor() as cur:
        await cur.execute(
            """INSERT INTO terminals (id, name, icon, last_connection)
               VALUES (%(id)s, %(name)s, %(icon)s, %(last_connection)s)""",
            terminal,
        )


_UPDATABLE_COLUMNS = {"name", "icon", "last_connection"}


async def update(conn: AsyncConnection, id: str, data: dict):
    set_clauses = []
    params = {"_id": id}
    for key, value in data.items():
        if key not in _UPDATABLE_COLUMNS:
            raise ValueError(f"Invalid column: {key}")
        set_clauses.append(f"{key} = %({key})s")
        params[key] = value
    if not set_clauses:
        return
    sql = f"UPDATE terminals SET {', '.join(set_clauses)} WHERE id = %(_id)s"
    async with conn.cursor() as cur:
        await cur.execute(sql, params)


async def remove(conn: AsyncConnection, id: str):
    async with conn.cursor() as cur:
        await cur.execute("DELETE FROM terminals WHERE id = %(id)s", {"id": id})


async def count(conn: AsyncConnection) -> int:
    async with conn.cursor() as cur:
        await cur.execute("SELECT COUNT(*) FROM terminals")
        row = await cur.fetchone()
        return row[0]
