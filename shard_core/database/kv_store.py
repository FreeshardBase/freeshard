import logging

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

log = logging.getLogger(__name__)


async def get_value(conn: AsyncConnection, key: str):
    async with conn.cursor() as cur:
        await cur.execute(
            "SELECT value FROM kv_store WHERE key = %(key)s", {"key": key}
        )
        row = await cur.fetchone()
        if row:
            return row[0]
        raise KeyError(key)


async def set_value(conn: AsyncConnection, key: str, value):
    async with conn.cursor() as cur:
        await cur.execute(
            """INSERT INTO kv_store (key, value)
               VALUES (%(key)s, %(value)s)
               ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value""",
            {"key": key, "value": Jsonb(value)},
        )


async def remove_value(conn: AsyncConnection, key: str) -> bool:
    async with conn.cursor() as cur:
        await cur.execute("DELETE FROM kv_store WHERE key = %(key)s", {"key": key})
        return cur.rowcount > 0
