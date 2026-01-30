"""
Database access methods for backup reports
"""
import json
from datetime import datetime
from typing import List, Dict, Any, Optional

from shard_core.db.db_connection import get_cursor


def get_all() -> List[Dict[str, Any]]:
    """Get all backup reports"""
    with get_cursor() as cur:
        cur.execute("SELECT * FROM backup_reports ORDER BY end_time DESC")
        return cur.fetchall()


def get_latest() -> Optional[Dict[str, Any]]:
    """Get the latest backup report"""
    with get_cursor() as cur:
        cur.execute("SELECT * FROM backup_reports ORDER BY end_time DESC LIMIT 1")
        return cur.fetchone()


def insert(directory: str, start_time: datetime, end_time: datetime, stats: Dict[str, Any]) -> None:
    """Insert a new backup report"""
    # Convert stats dict to JSON
    stats_json = json.dumps(stats) if isinstance(stats, dict) else stats
    
    with get_cursor() as cur:
        cur.execute(
            """
            INSERT INTO backup_reports (directory, start_time, end_time, stats)
            VALUES (%s, %s, %s, %s)
            """,
            (directory, start_time, end_time, stats_json),
        )
