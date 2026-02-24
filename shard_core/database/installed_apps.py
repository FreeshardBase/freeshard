import logging
from datetime import datetime
from typing import Optional

from psycopg import AsyncConnection
from psycopg.rows import dict_row

log = logging.getLogger(__name__)


async def get_all(conn: AsyncConnection) -> list[dict]:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute("SELECT * FROM installed_apps")
        return await cur.fetchall()


async def get_by_name(conn: AsyncConnection, name: str) -> Optional[dict]:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute("SELECT * FROM installed_apps WHERE name = %(name)s", {"name": name})
        return await cur.fetchone()


async def insert(conn: AsyncConnection, app: dict):
    async with conn.cursor() as cur:
        await cur.execute(
            """INSERT INTO installed_apps (name, installation_reason, status, last_access)
               VALUES (%(name)s, %(installation_reason)s, %(status)s, %(last_access)s)""",
            app,
        )


async def update_status(conn: AsyncConnection, name: str, status: str) -> int:
    async with conn.cursor() as cur:
        await cur.execute(
            "UPDATE installed_apps SET status = %(status)s WHERE name = %(name)s",
            {"name": name, "status": status},
        )
        return cur.rowcount


async def update(conn: AsyncConnection, name: str, data: dict):
    async with conn.cursor() as cur:
        await cur.execute(
            """UPDATE installed_apps
               SET installation_reason = %(installation_reason)s,
                   status = %(status)s,
                   last_access = %(last_access)s
               WHERE name = %(name)s""",
            {"name": name, **data},
        )


async def update_last_access(conn: AsyncConnection, name: str, last_access: datetime):
    async with conn.cursor() as cur:
        await cur.execute(
            "UPDATE installed_apps SET last_access = %(last_access)s WHERE name = %(name)s",
            {"name": name, "last_access": last_access},
        )


async def contains(conn: AsyncConnection, name: str) -> bool:
    async with conn.cursor() as cur:
        await cur.execute("SELECT 1 FROM installed_apps WHERE name = %(name)s", {"name": name})
        return await cur.fetchone() is not None


async def remove(conn: AsyncConnection, name: str):
    async with conn.cursor() as cur:
        await cur.execute("DELETE FROM installed_apps WHERE name = %(name)s", {"name": name})


async def count(conn: AsyncConnection) -> int:
    async with conn.cursor() as cur:
        await cur.execute("SELECT COUNT(*) FROM installed_apps")
        row = await cur.fetchone()
        return row[0]
