from typing import LiteralString

from psycopg import AsyncConnection
from psycopg.rows import dict_row


async def get_by_id(conn: AsyncConnection, id: str) -> dict | None:
    sql: LiteralString = "SELECT * FROM users WHERE id = %s"
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(sql, (id,))
        return await cur.fetchone()


async def get_owner(conn: AsyncConnection) -> dict | None:
    sql: LiteralString = "SELECT * FROM users WHERE role = 'owner'"
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(sql)
        return await cur.fetchone()


async def insert(conn: AsyncConnection, user: dict) -> dict:
    sql: LiteralString = """INSERT INTO users (id, username, display_name, email, role)
        VALUES (%(id)s, %(username)s, %(display_name)s, %(email)s, %(role)s)
        RETURNING *"""
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(sql, user)
        return await cur.fetchone()


async def count(conn: AsyncConnection) -> int:
    sql: LiteralString = "SELECT COUNT(*) FROM users"
    async with conn.cursor() as cur:
        await cur.execute(sql)
        return (await cur.fetchone())[0]
