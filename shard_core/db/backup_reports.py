"""
Database access methods for backup reports
"""
import json
from datetime import datetime
from typing import List, Dict, Any, Optional

from psycopg import AsyncConnection
from psycopg.rows import class_row

from shard_core.data_model.backup import BackupReport


async def get_all(conn: AsyncConnection) -> List[BackupReport]:
    """Get all backup reports"""
    async with conn.cursor(row_factory=class_row(BackupReport)) as cur:
        await cur.execute("SELECT start_time as \"startTime\", end_time as \"endTime\", directories FROM backup_reports ORDER BY end_time DESC")
        return await cur.fetchall()


async def get_latest(conn: AsyncConnection) -> Optional[BackupReport]:
    """Get the latest backup report"""
    async with conn.cursor(row_factory=class_row(BackupReport)) as cur:
        await cur.execute("SELECT start_time as \"startTime\", end_time as \"endTime\", directories FROM backup_reports ORDER BY end_time DESC LIMIT 1")
        return await cur.fetchone()


async def insert(conn: AsyncConnection, start_time: datetime, end_time: datetime, directories: List[Dict[str, Any]]) -> None:
    """Insert a new backup report"""
    # Convert directories list to JSON
    directories_json = json.dumps(directories) if isinstance(directories, list) else directories
    
    async with conn.cursor() as cur:
        await cur.execute(
            """
            INSERT INTO backup_reports (start_time, end_time, directories)
            VALUES (%s, %s, %s)
            """,
            (start_time, end_time, directories_json),
        )
