from typing import LiteralString

from psycopg import AsyncConnection
from psycopg.rows import dict_row

_UPDATABLE_COLUMNS = {"name", "public_bytes_b64", "is_reachable"}


async def get_all(conn: AsyncConnection) -> list[dict]:
    sql: LiteralString = "SELECT * FROM peers"
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(sql)
        return await cur.fetchall()


async def get_by_id_prefix(conn: AsyncConnection, id_prefix: str) -> dict | None:
    sql: LiteralString = "SELECT * FROM peers WHERE id LIKE %s LIMIT 1"
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(sql, (f"{id_prefix}%",))
        return await cur.fetchone()


async def search_by_name(conn: AsyncConnection, name: str) -> list[dict]:
    sql: LiteralString = "SELECT * FROM peers WHERE name ILIKE %s"
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(sql, (f"%{name}%",))
        return await cur.fetchall()


async def insert(conn: AsyncConnection, peer: dict) -> dict:
    sql: LiteralString = """INSERT INTO peers (id, name, public_bytes_b64, is_reachable)
        VALUES (%(id)s, %(name)s, %(public_bytes_b64)s, %(is_reachable)s)
        RETURNING *"""
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(sql, peer)
        return await cur.fetchone()


async def upsert(conn: AsyncConnection, peer: dict) -> dict:
    sql: LiteralString = """INSERT INTO peers (id, name, public_bytes_b64, is_reachable)
        VALUES (%(id)s, %(name)s, %(public_bytes_b64)s, %(is_reachable)s)
        ON CONFLICT (id) DO UPDATE SET
            name = EXCLUDED.name,
            public_bytes_b64 = EXCLUDED.public_bytes_b64,
            is_reachable = EXCLUDED.is_reachable
        RETURNING *"""
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(sql, peer)
        return await cur.fetchone()


async def update_by_id(conn: AsyncConnection, id: str, data: dict) -> dict | None:
    set_clauses = []
    params = {"_id": id}
    for key, value in data.items():
        if key not in _UPDATABLE_COLUMNS:
            raise ValueError(f"Invalid column: {key}")
        set_clauses.append(f"{key} = %({key})s")
        params[key] = value
    if not set_clauses:
        return None
    sql = f"UPDATE peers SET {', '.join(set_clauses)} WHERE id = %(_id)s RETURNING *"
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(sql, params)
        return await cur.fetchone()


async def update_by_id_prefix(
    conn: AsyncConnection, id_prefix: str, data: dict
) -> dict | None:
    set_clauses = []
    params = {"_pattern": f"{id_prefix}%"}
    for key, value in data.items():
        if key not in _UPDATABLE_COLUMNS:
            raise ValueError(f"Invalid column: {key}")
        set_clauses.append(f"{key} = %({key})s")
        params[key] = value
    if not set_clauses:
        return None
    sql = f"UPDATE peers SET {', '.join(set_clauses)} WHERE id LIKE %(_pattern)s RETURNING *"
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(sql, params)
        return await cur.fetchone()


async def remove_by_id_prefix(conn: AsyncConnection, id_prefix: str) -> int:
    sql: LiteralString = "DELETE FROM peers WHERE id LIKE %s"
    result = await conn.execute(sql, (f"{id_prefix}%",))
    return result.rowcount
