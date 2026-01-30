"""
Database access methods for app usage tracking
"""
import json
from datetime import datetime
from typing import List, Dict, Any

from shard_core.db.db_connection import get_cursor


def get_all() -> List[Dict[str, Any]]:
    """Get all app usage tracks"""
    with get_cursor() as cur:
        cur.execute("SELECT * FROM app_usage_track ORDER BY timestamp DESC")
        return cur.fetchall()


def insert(track: Dict[str, Any]) -> None:
    """Insert a new app usage track"""
    # Convert installed_apps list to JSON
    if 'installed_apps' in track:
        track['installed_apps'] = json.dumps(track['installed_apps']) if isinstance(track['installed_apps'], list) else track['installed_apps']
    
    with get_cursor() as cur:
        cur.execute(
            """
            INSERT INTO app_usage_track (timestamp, installed_apps)
            VALUES (%(timestamp)s, %(installed_apps)s)
            """,
            track,
        )
