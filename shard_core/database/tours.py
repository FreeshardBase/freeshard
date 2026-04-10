from typing import LiteralString

from psycopg import AsyncConnection
from psycopg.rows import dict_row


async def get_all(conn: AsyncConnection) -> list[dict]:
    sql: LiteralString = "SELECT * FROM tours"
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(sql)
        return await cur.fetchall()


async def get_by_name(conn: AsyncConnection, name: str) -> dict | None:
    sql: LiteralString = "SELECT * FROM tours WHERE name = %s"
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(sql, (name,))
        return await cur.fetchone()


async def upsert(conn: AsyncConnection, tour: dict) -> dict:
    sql: LiteralString = """INSERT INTO tours (name, status)
        VALUES (%(name)s, %(status)s)
        ON CONFLICT (name) DO UPDATE SET status = EXCLUDED.status
        RETURNING *"""
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(sql, tour)
        return await cur.fetchone()


async def truncate(conn: AsyncConnection):
    sql: LiteralString = "DELETE FROM tours"
    await conn.execute(sql)
