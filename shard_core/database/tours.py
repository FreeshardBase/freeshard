import logging
from typing import Optional

from psycopg import AsyncConnection
from psycopg.rows import dict_row

log = logging.getLogger(__name__)


async def get_all(conn: AsyncConnection) -> list[dict]:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute("SELECT * FROM tours")
        return await cur.fetchall()


async def get_by_name(conn: AsyncConnection, name: str) -> Optional[dict]:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute("SELECT * FROM tours WHERE name = %(name)s", {"name": name})
        return await cur.fetchone()


async def upsert(conn: AsyncConnection, tour: dict):
    async with conn.cursor() as cur:
        await cur.execute(
            """INSERT INTO tours (name, status)
               VALUES (%(name)s, %(status)s)
               ON CONFLICT (name) DO UPDATE SET status = EXCLUDED.status""",
            tour,
        )


async def truncate(conn: AsyncConnection):
    async with conn.cursor() as cur:
        await cur.execute("DELETE FROM tours")
