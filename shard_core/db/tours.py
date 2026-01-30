"""
Database access methods for tours
"""
from datetime import datetime
from typing import List, Dict, Any, Optional

from shard_core.db.db_connection import get_cursor


def get_all() -> List[Dict[str, Any]]:
    """Get all tours"""
    with get_cursor() as cur:
        cur.execute("SELECT * FROM tours ORDER BY created_at")
        return cur.fetchall()


def get_by_id(tour_id: str) -> Optional[Dict[str, Any]]:
    """Get tour by id"""
    with get_cursor() as cur:
        cur.execute("SELECT * FROM tours WHERE id = %s", (tour_id,))
        return cur.fetchone()


def insert(tour: Dict[str, Any]) -> None:
    """Insert a new tour"""
    with get_cursor() as cur:
        cur.execute(
            """
            INSERT INTO tours (id, completed)
            VALUES (%(id)s, %(completed)s)
            ON CONFLICT (id) DO UPDATE SET
                completed = EXCLUDED.completed,
                updated_at = CURRENT_TIMESTAMP
            """,
            tour,
        )


def update(
    tour_id: str,
    *,
    completed: Optional[bool] = None
) -> None:
    """Update a tour with typed parameters"""
    if completed is None:
        return
    
    params = {
        'id': tour_id,
        'completed': completed,
        'updated_at': datetime.utcnow()
    }
    
    with get_cursor() as cur:
        cur.execute(
            "UPDATE tours SET completed = %(completed)s, updated_at = %(updated_at)s WHERE id = %(id)s",
            params,
        )


def delete(tour_id: str) -> None:
    """Delete a tour"""
    with get_cursor() as cur:
        cur.execute("DELETE FROM tours WHERE id = %s", (tour_id,))


def count() -> int:
    """Count all tours"""
    with get_cursor() as cur:
        cur.execute("SELECT COUNT(*) as count FROM tours")
        return cur.fetchone()['count']


def delete_all() -> None:
    """Delete all tours"""
    with get_cursor() as cur:
        cur.execute("DELETE FROM tours")
