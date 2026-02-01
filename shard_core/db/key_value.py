"""
Database access methods for key-value storage
"""
import json
from typing import Any

from psycopg import AsyncConnection


async def get(conn: AsyncConnection, key: str) -> Any:
    """Get value by key"""
    async with conn.cursor() as cur:
        await cur.execute("SELECT value FROM key_value WHERE key = %s", (key,))
        row = await cur.fetchone()
        if row:
            return row[0]
        else:
            raise KeyError(key)


async def set(conn: AsyncConnection, key: str, value: Any) -> None:
    """Set or update a key-value pair"""
    # Convert value to JSON
    json_value = json.dumps(value)
    
    async with conn.cursor() as cur:
        await cur.execute(
            """
            INSERT INTO key_value (key, value)
            VALUES (%s, %s)
            ON CONFLICT (key) DO UPDATE SET
                value = EXCLUDED.value,
                updated_at = CURRENT_TIMESTAMP
            """,
            (key, json_value),
        )


async def remove(conn: AsyncConnection, key: str) -> bool:
    """Remove a key-value pair, returns True if removed"""
    async with conn.cursor() as cur:
        await cur.execute("DELETE FROM key_value WHERE key = %s RETURNING key", (key,))
        return await cur.fetchone() is not None
