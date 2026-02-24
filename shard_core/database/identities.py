import logging
from typing import Optional

from psycopg import AsyncConnection
from psycopg.rows import dict_row

log = logging.getLogger(__name__)


async def get_all(conn: AsyncConnection) -> list[dict]:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute("SELECT * FROM identities")
        return await cur.fetchall()


async def get_by_id(conn: AsyncConnection, id: str) -> Optional[dict]:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute("SELECT * FROM identities WHERE id = %(id)s", {"id": id})
        return await cur.fetchone()


async def get_default(conn: AsyncConnection) -> Optional[dict]:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute("SELECT * FROM identities WHERE is_default = TRUE")
        return await cur.fetchone()


async def search_by_name(conn: AsyncConnection, name: str) -> list[dict]:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT * FROM identities WHERE name ILIKE %(pattern)s",
            {"pattern": f"%{name}%"},
        )
        return await cur.fetchall()


async def insert(conn: AsyncConnection, identity: dict):
    async with conn.cursor() as cur:
        await cur.execute(
            """INSERT INTO identities (id, name, email, description, private_key, is_default)
               VALUES (%(id)s, %(name)s, %(email)s, %(description)s, %(private_key)s, %(is_default)s)""",
            identity,
        )


async def update(conn: AsyncConnection, id: str, data: dict):
    set_clauses = []
    params = {"_id": id}
    for key, value in data.items():
        set_clauses.append(f"{key} = %({key})s")
        params[key] = value
    if not set_clauses:
        return
    sql = f"UPDATE identities SET {', '.join(set_clauses)} WHERE id = %(_id)s"
    async with conn.cursor() as cur:
        await cur.execute(sql, params)


async def count(conn: AsyncConnection) -> int:
    async with conn.cursor() as cur:
        await cur.execute("SELECT COUNT(*) FROM identities")
        row = await cur.fetchone()
        return row[0]
