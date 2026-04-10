import json
from datetime import datetime
from typing import LiteralString

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb


class _DateTimeEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)


async def get_value(conn: AsyncConnection, key: str):
    sql: LiteralString = "SELECT value FROM kv_store WHERE key = %s"
    async with conn.cursor() as cur:
        await cur.execute(sql, (key,))
        row = await cur.fetchone()
        if row:
            return row[0]
        raise KeyError(key)


async def set_value(conn: AsyncConnection, key: str, value):
    sql: LiteralString = """INSERT INTO kv_store (key, value)
        VALUES (%(key)s, %(value)s)
        ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value"""
    await conn.execute(
        sql,
        {
            "key": key,
            "value": Jsonb(value, dumps=lambda v: json.dumps(v, cls=_DateTimeEncoder)),
        },
    )


async def remove_value(conn: AsyncConnection, key: str) -> bool:
    sql: LiteralString = "DELETE FROM kv_store WHERE key = %s"
    result = await conn.execute(sql, (key,))
    return result.rowcount > 0
