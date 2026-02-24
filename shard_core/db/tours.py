"""
Database access methods for tours
"""
from datetime import datetime
from typing import List, Dict, Any, Optional

from psycopg import AsyncConnection


async def get_all(conn: AsyncConnection) -> List[Dict[str, Any]]:
    """Get all tours"""
    async with conn.cursor() as cur:
        await cur.execute("SELECT * FROM tours ORDER BY created_at")
        rows = await cur.fetchall()
        return [dict(row) for row in rows]


async def get_by_id(conn: AsyncConnection, tour_id: str) -> Optional[Dict[str, Any]]:
    """Get tour by id"""
    async with conn.cursor() as cur:
        await cur.execute("SELECT * FROM tours WHERE id = %s", (tour_id,))
        row = await cur.fetchone()
        return dict(row) if row else None


async def insert(conn: AsyncConnection, tour: Dict[str, Any]) -> None:
    """Insert a new tour"""
    async with conn.cursor() as cur:
        await cur.execute(
            """
            INSERT INTO tours (id, completed)
            VALUES (%(id)s, %(completed)s)
            ON CONFLICT (id) DO UPDATE SET
                completed = EXCLUDED.completed,
                updated_at = CURRENT_TIMESTAMP
            """,
            tour,
        )


async def update(
    conn: AsyncConnection,
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
    
    async with conn.cursor() as cur:
        await cur.execute(
            "UPDATE tours SET completed = %(completed)s, updated_at = %(updated_at)s WHERE id = %(id)s",
            params,
        )


async def delete(conn: AsyncConnection, tour_id: str) -> None:
    """Delete a tour"""
    async with conn.cursor() as cur:
        await cur.execute("DELETE FROM tours WHERE id = %s", (tour_id,))


async def count(conn: AsyncConnection) -> int:
    """Count all tours"""
    async with conn.cursor() as cur:
        await cur.execute("SELECT COUNT(*) as count FROM tours")
        result = await cur.fetchone()
        return result[0]


async def delete_all(conn: AsyncConnection) -> None:
    """Delete all tours"""
    async with conn.cursor() as cur:
        await cur.execute("DELETE FROM tours")
