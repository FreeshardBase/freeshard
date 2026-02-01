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


def insert(start_time: datetime, end_time: datetime, directories: List[Dict[str, Any]]) -> None:
    """Insert a new backup report"""
    # Convert directories list to JSON
    directories_json = json.dumps(directories) if isinstance(directories, list) else directories
    
    with get_cursor() as cur:
        cur.execute(
            """
            INSERT INTO backup_reports (start_time, end_time, directories)
            VALUES (%s, %s, %s)
            """,
            (start_time, end_time, directories_json),
        )
