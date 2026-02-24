import logging
from typing import Optional

from psycopg import AsyncConnection
from psycopg.rows import dict_row

log = logging.getLogger(__name__)


async def get_all(conn: AsyncConnection) -> list[dict]:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute("SELECT * FROM peers")
        return await cur.fetchall()


async def get_by_id_prefix(conn: AsyncConnection, id_prefix: str) -> Optional[dict]:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT * FROM peers WHERE id LIKE %(pattern)s LIMIT 1",
            {"pattern": f"{id_prefix}:%"},
        )
        return await cur.fetchone()


async def search_by_name(conn: AsyncConnection, name: str) -> list[dict]:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT * FROM peers WHERE name ILIKE %(pattern)s",
            {"pattern": f"%{name}%"},
        )
        return await cur.fetchall()


async def insert(conn: AsyncConnection, peer: dict):
    async with conn.cursor() as cur:
        await cur.execute(
            """INSERT INTO peers (id, name, public_bytes_b64, is_reachable)
               VALUES (%(id)s, %(name)s, %(public_bytes_b64)s, %(is_reachable)s)""",
            peer,
        )


async def upsert(conn: AsyncConnection, peer: dict):
    async with conn.cursor() as cur:
        await cur.execute(
            """INSERT INTO peers (id, name, public_bytes_b64, is_reachable)
               VALUES (%(id)s, %(name)s, %(public_bytes_b64)s, %(is_reachable)s)
               ON CONFLICT (id) DO UPDATE SET
                   name = EXCLUDED.name,
                   public_bytes_b64 = EXCLUDED.public_bytes_b64,
                   is_reachable = EXCLUDED.is_reachable""",
            peer,
        )


_UPDATABLE_COLUMNS = {"name", "public_bytes_b64", "is_reachable"}


async def update_by_id(conn: AsyncConnection, id: str, data: dict):
    set_clauses = []
    params = {"_id": id}
    for key, value in data.items():
        if key not in _UPDATABLE_COLUMNS:
            raise ValueError(f"Invalid column: {key}")
        set_clauses.append(f"{key} = %({key})s")
        params[key] = value
    if not set_clauses:
        return
    sql = f"UPDATE peers SET {', '.join(set_clauses)} WHERE id = %(_id)s"
    async with conn.cursor() as cur:
        await cur.execute(sql, params)


async def update_by_id_prefix(conn: AsyncConnection, id_prefix: str, data: dict):
    set_clauses = []
    params = {"_pattern": f"{id_prefix}:%"}
    for key, value in data.items():
        if key not in _UPDATABLE_COLUMNS:
            raise ValueError(f"Invalid column: {key}")
        set_clauses.append(f"{key} = %({key})s")
        params[key] = value
    if not set_clauses:
        return
    sql = f"UPDATE peers SET {', '.join(set_clauses)} WHERE id LIKE %(_pattern)s"
    async with conn.cursor() as cur:
        await cur.execute(sql, params)


async def remove_by_id_prefix(conn: AsyncConnection, id_prefix: str) -> int:
    async with conn.cursor() as cur:
        await cur.execute(
            "DELETE FROM peers WHERE id LIKE %(pattern)s",
            {"pattern": f"{id_prefix}:%"},
        )
        return cur.rowcount
