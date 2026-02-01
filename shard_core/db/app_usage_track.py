"""
Database access methods for app usage tracking
"""
import json
from typing import List

from psycopg import AsyncConnection
from psycopg.rows import class_row

from shard_core.data_model.app_usage import AppUsageTrack


async def get_all(conn: AsyncConnection) -> List[AppUsageTrack]:
    """Get all app usage tracks"""
    async with conn.cursor(row_factory=class_row(AppUsageTrack)) as cur:
        await cur.execute("SELECT timestamp, installed_apps FROM app_usage_track ORDER BY timestamp DESC")
        return await cur.fetchall()


async def insert(conn: AsyncConnection, track: AppUsageTrack) -> None:
    """Insert a new app usage track"""
    # Convert installed_apps list to JSON
    installed_apps_json = json.dumps(track.installed_apps)
    
    async with conn.cursor() as cur:
        await cur.execute(
            """
            INSERT INTO app_usage_track (timestamp, installed_apps)
            VALUES (%s, %s)
            """,
            (track.timestamp, installed_apps_json),
        )
