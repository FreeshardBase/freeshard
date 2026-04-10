from typing import LiteralString

from psycopg import AsyncConnection
from psycopg.rows import dict_row

_UPDATABLE_COLUMNS = {"name", "email", "description", "private_key", "is_default"}


async def get_all(conn: AsyncConnection) -> list[dict]:
    sql: LiteralString = "SELECT * FROM identities"
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(sql)
        return await cur.fetchall()


async def get_by_id(conn: AsyncConnection, id: str) -> dict | None:
    sql: LiteralString = "SELECT * FROM identities WHERE id = %s"
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(sql, (id,))
        return await cur.fetchone()


async def get_default(conn: AsyncConnection) -> dict | None:
    sql: LiteralString = "SELECT * FROM identities WHERE is_default = TRUE"
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(sql)
        return await cur.fetchone()


async def search_by_name(conn: AsyncConnection, name: str) -> list[dict]:
    sql: LiteralString = "SELECT * FROM identities WHERE name ILIKE %s"
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(sql, (f"%{name}%",))
        return await cur.fetchall()


async def insert(conn: AsyncConnection, identity: dict) -> dict:
    sql: LiteralString = """INSERT INTO identities (id, name, email, description, private_key, is_default)
        VALUES (%(id)s, %(name)s, %(email)s, %(description)s, %(private_key)s, %(is_default)s)
        RETURNING *"""
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(sql, identity)
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
        f"UPDATE identities SET {', '.join(set_clauses)} WHERE id = %(_id)s RETURNING *"
    )
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(sql, params)
        return await cur.fetchone()


async def count(conn: AsyncConnection) -> int:
    sql: LiteralString = "SELECT COUNT(*) FROM identities"
    async with conn.cursor() as cur:
        await cur.execute(sql)
        return (await cur.fetchone())[0]
