"""
Database access methods for key-value storage
"""
import json
from typing import Any

from shard_core.db.db_connection import get_cursor


def get(key: str) -> Any:
    """Get value by key"""
    with get_cursor() as cur:
        cur.execute("SELECT value FROM key_value WHERE key = %s", (key,))
        result = cur.fetchone()
        if result:
            return result['value']
        else:
            raise KeyError(key)


def set(key: str, value: Any) -> None:
    """Set or update a key-value pair"""
    # Convert value to JSON
    json_value = json.dumps(value)
    
    with get_cursor() as cur:
        cur.execute(
            """
            INSERT INTO key_value (key, value)
            VALUES (%s, %s)
            ON CONFLICT (key) DO UPDATE SET
                value = EXCLUDED.value,
                updated_at = CURRENT_TIMESTAMP
            """,
            (key, json_value),
        )


def remove(key: str) -> bool:
    """Remove a key-value pair, returns True if removed"""
    with get_cursor() as cur:
        cur.execute("DELETE FROM key_value WHERE key = %s RETURNING key", (key,))
        return cur.fetchone() is not None
