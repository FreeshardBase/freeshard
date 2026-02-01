"""
Database access methods for peers
"""
from datetime import datetime
from typing import List, Optional

from psycopg import AsyncConnection
from psycopg.rows import class_row

from shard_core.data_model.peer import Peer


async def get_all(conn: AsyncConnection) -> List[Peer]:
    """Get all peers"""
    async with conn.cursor(row_factory=class_row(Peer)) as cur:
        await cur.execute("SELECT * FROM peers ORDER BY created_at")
        return await cur.fetchall()


async def get_by_id(conn: AsyncConnection, peer_id: str) -> Optional[Peer]:
    """Get peer by id (supports partial match with wildcard)"""
    async with conn.cursor(row_factory=class_row(Peer)) as cur:
        # First try exact match
        await cur.execute("SELECT * FROM peers WHERE id = %s", (peer_id,))
        result = await cur.fetchone()
        if result:
            return result
        
        # Try prefix match
        await cur.execute("SELECT * FROM peers WHERE id LIKE %s LIMIT 1", (f"{peer_id}:%",))
        return await cur.fetchone()


async def insert(conn: AsyncConnection, peer: Peer) -> None:
    """Insert a new peer"""
    async with conn.cursor() as cur:
        await cur.execute(
            """
            INSERT INTO peers (id, name, public_bytes_b64, is_reachable)
            VALUES (%s, %s, %s, %s)
            """,
            (peer.id, peer.name, peer.public_bytes_b64, peer.is_reachable),
        )


async def update(
    conn: AsyncConnection,
    peer_id: str,
    *,
    name: Optional[str] = None,
    public_bytes_b64: Optional[str] = None,
    is_reachable: Optional[bool] = None
) -> None:
    """Update a peer with typed parameters"""
    updates = {}
    if name is not None:
        updates['name'] = name
    if public_bytes_b64 is not None:
        updates['public_bytes_b64'] = public_bytes_b64
    if is_reachable is not None:
        updates['is_reachable'] = is_reachable
    
    if not updates:
        return
    
    set_parts = [f"{key} = %({key})s" for key in updates.keys()]
    params = updates.copy()
    params['id'] = peer_id
    params['updated_at'] = datetime.utcnow()
    set_parts.append("updated_at = %(updated_at)s")
    
    async with conn.cursor() as cur:
        await cur.execute(
            f"UPDATE peers SET {', '.join(set_parts)} WHERE id = %(id)s",
            params,
        )


async def delete(conn: AsyncConnection, peer_id: str) -> None:
    """Delete a peer"""
    async with conn.cursor() as cur:
        await cur.execute("DELETE FROM peers WHERE id = %s", (peer_id,))


async def search_without_pubkey(conn: AsyncConnection) -> List[Peer]:
    """Search for peers that don't have a public key"""
    async with conn.cursor(row_factory=class_row(Peer)) as cur:
        await cur.execute("SELECT * FROM peers WHERE public_bytes_b64 IS NOT NULL")
        return await cur.fetchall()
