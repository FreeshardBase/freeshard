"""
Database access methods for terminals
"""
from datetime import datetime
from typing import List, Dict, Any, Optional

from shard_core.db.db_connection import get_cursor


def get_all() -> List[Dict[str, Any]]:
    """Get all terminals"""
    with get_cursor() as cur:
        cur.execute("SELECT * FROM terminals ORDER BY last_connection DESC")
        return cur.fetchall()


def get_by_id(terminal_id: str) -> Optional[Dict[str, Any]]:
    """Get terminal by id"""
    with get_cursor() as cur:
        cur.execute("SELECT * FROM terminals WHERE id = %s", (terminal_id,))
        return cur.fetchone()


def insert(terminal: Dict[str, Any]) -> None:
    """Insert a new terminal"""
    with get_cursor() as cur:
        cur.execute(
            """
            INSERT INTO terminals (id, name, icon, last_connection)
            VALUES (%(id)s, %(name)s, %(icon)s, %(last_connection)s)
            """,
            terminal,
        )


def update(
    terminal_id: str,
    *,
    name: Optional[str] = None,
    icon: Optional[str] = None,
    last_connection: Optional[datetime] = None
) -> None:
    """Update a terminal with typed parameters"""
    updates = {}
    if name is not None:
        updates['name'] = name
    if icon is not None:
        updates['icon'] = icon
    if last_connection is not None:
        updates['last_connection'] = last_connection
    
    if not updates:
        return
    
    set_parts = [f"{key} = %({key})s" for key in updates.keys()]
    params = updates.copy()
    params['id'] = terminal_id
    params['updated_at'] = datetime.utcnow()
    set_parts.append("updated_at = %(updated_at)s")
    
    with get_cursor() as cur:
        cur.execute(
            f"UPDATE terminals SET {', '.join(set_parts)} WHERE id = %(id)s",
            params,
        )


def delete(terminal_id: str) -> None:
    """Delete a terminal"""
    with get_cursor() as cur:
        cur.execute("DELETE FROM terminals WHERE id = %s", (terminal_id,))


def count() -> int:
    """Count all terminals"""
    with get_cursor() as cur:
        cur.execute("SELECT COUNT(*) as count FROM terminals")
        return cur.fetchone()['count']
