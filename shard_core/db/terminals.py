"""
Database access methods for terminals
"""
from datetime import datetime
from typing import List, Optional

from psycopg import AsyncConnection
from psycopg.rows import class_row

from shard_core.data_model.terminal import Terminal


async def get_all(conn: AsyncConnection) -> List[Terminal]:
    """Get all terminals"""
    async with conn.cursor(row_factory=class_row(Terminal)) as cur:
        await cur.execute("SELECT * FROM terminals ORDER BY last_connection DESC")
        return await cur.fetchall()


async def get_by_id(conn: AsyncConnection, terminal_id: str) -> Optional[Terminal]:
    """Get terminal by id"""
    async with conn.cursor(row_factory=class_row(Terminal)) as cur:
        await cur.execute("SELECT * FROM terminals WHERE id = %s", (terminal_id,))
        return await cur.fetchone()


async def insert(conn: AsyncConnection, terminal: Terminal) -> None:
    """Insert a new terminal"""
    async with conn.cursor() as cur:
        await cur.execute(
            """
            INSERT INTO terminals (id, name, icon, last_connection)
            VALUES (%s, %s, %s, %s)
            """,
            (terminal.id, terminal.name, terminal.icon.value, terminal.last_connection),
        )


async def update(
    conn: AsyncConnection,
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
    
    async with conn.cursor() as cur:
        await cur.execute(
            f"UPDATE terminals SET {', '.join(set_parts)} WHERE id = %(id)s",
            params,
        )


async def delete(conn: AsyncConnection, terminal_id: str) -> None:
    """Delete a terminal"""
    async with conn.cursor() as cur:
        await cur.execute("DELETE FROM terminals WHERE id = %s", (terminal_id,))


async def count(conn: AsyncConnection) -> int:
    """Count all terminals"""
    async with conn.cursor() as cur:
        await cur.execute("SELECT COUNT(*) as count FROM terminals")
        result = await cur.fetchone()
        return result[0]
