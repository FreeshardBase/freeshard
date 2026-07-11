from typing import LiteralString

from psycopg import AsyncConnection
from psycopg.rows import class_row

from shard_core.data_model.user import User

_UPDATABLE_COLUMNS = {"username", "display_name", "email", "role", "disabled"}


async def get_by_id(conn: AsyncConnection, id: int) -> User | None:
    sql: LiteralString = "SELECT * FROM users WHERE id = %s"
    async with conn.cursor(row_factory=class_row(User)) as cur:
        await cur.execute(sql, (id,))
        return await cur.fetchone()


async def get_owner(conn: AsyncConnection) -> User | None:
    sql: LiteralString = "SELECT * FROM users WHERE role = 'owner'"
    async with conn.cursor(row_factory=class_row(User)) as cur:
        await cur.execute(sql)
        return await cur.fetchone()


async def insert(conn: AsyncConnection, user: dict) -> User:
    sql: LiteralString = """INSERT INTO users (username, display_name, email, role)
        VALUES (%(username)s, %(display_name)s, %(email)s, %(role)s)
        RETURNING *"""
    async with conn.cursor(row_factory=class_row(User)) as cur:
        await cur.execute(sql, user)
        return await cur.fetchone()


async def update(conn: AsyncConnection, id: int, data: dict) -> User | None:
    set_clauses = []
    params = {"_id": id}
    for key, value in data.items():
        if key not in _UPDATABLE_COLUMNS:
            raise ValueError(f"Invalid column: {key}")
        set_clauses.append(f"{key} = %({key})s")
        params[key] = value
    if not set_clauses:
        return await get_by_id(conn, id)
    sql = f"UPDATE users SET {', '.join(set_clauses)} WHERE id = %(_id)s RETURNING *"
    async with conn.cursor(row_factory=class_row(User)) as cur:
        await cur.execute(sql, params)
        return await cur.fetchone()


async def count(conn: AsyncConnection) -> int:
    sql: LiteralString = "SELECT COUNT(*) FROM users"
    async with conn.cursor() as cur:
        await cur.execute(sql)
        return (await cur.fetchone())[0]
