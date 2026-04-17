from datetime import datetime
from typing import LiteralString

from psycopg import AsyncConnection
from psycopg.rows import dict_row


async def get_all(conn: AsyncConnection) -> list[dict]:
    sql: LiteralString = "SELECT * FROM installed_apps"
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(sql)
        return await cur.fetchall()


async def get_by_name(conn: AsyncConnection, name: str) -> dict | None:
    sql: LiteralString = "SELECT * FROM installed_apps WHERE name = %s"
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(sql, (name,))
        return await cur.fetchone()


async def insert(conn: AsyncConnection, app: dict) -> dict:
    sql: LiteralString = """INSERT INTO installed_apps (name, installation_reason, status, last_access)
        VALUES (%(name)s, %(installation_reason)s, %(status)s, %(last_access)s)
        RETURNING *"""
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(sql, app)
        return await cur.fetchone()


async def update_status(conn: AsyncConnection, name: str, status: str) -> dict | None:
    sql: LiteralString = (
        "UPDATE installed_apps SET status = %(status)s WHERE name = %(name)s RETURNING *"
    )
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(sql, {"name": name, "status": status})
        return await cur.fetchone()


async def update_last_access(
    conn: AsyncConnection, name: str, last_access: datetime
) -> dict | None:
    sql: LiteralString = (
        "UPDATE installed_apps SET last_access = %(last_access)s WHERE name = %(name)s RETURNING *"
    )
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(sql, {"name": name, "last_access": last_access})
        return await cur.fetchone()


async def contains(conn: AsyncConnection, name: str) -> bool:
    sql: LiteralString = "SELECT 1 FROM installed_apps WHERE name = %s"
    async with conn.cursor() as cur:
        await cur.execute(sql, (name,))
        return await cur.fetchone() is not None


async def remove(conn: AsyncConnection, name: str):
    sql: LiteralString = "DELETE FROM installed_apps WHERE name = %s"
    await conn.execute(sql, (name,))


async def count(conn: AsyncConnection) -> int:
    sql: LiteralString = "SELECT COUNT(*) FROM installed_apps"
    async with conn.cursor() as cur:
        await cur.execute(sql)
        return (await cur.fetchone())[0]
