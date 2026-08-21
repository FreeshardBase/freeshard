from typing import LiteralString

from psycopg import AsyncConnection


async def get_all_for_app(conn: AsyncConnection, app_name: str) -> dict[str, str]:
    sql: LiteralString = "SELECT name, value FROM app_secrets WHERE app_name = %s"
    async with conn.cursor() as cur:
        await cur.execute(sql, (app_name,))
        return {name: value for name, value in await cur.fetchall()}


async def insert(conn: AsyncConnection, app_name: str, name: str, value: str):
    sql: LiteralString = """INSERT INTO app_secrets (app_name, name, value)
        VALUES (%(app_name)s, %(name)s, %(value)s)
        ON CONFLICT (app_name, name) DO NOTHING"""
    await conn.execute(sql, {"app_name": app_name, "name": name, "value": value})
