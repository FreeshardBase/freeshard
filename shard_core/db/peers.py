"""
Database access methods for peers
"""
from datetime import datetime
from typing import List, Dict, Any, Optional

from shard_core.db.db_connection import get_cursor


def get_all() -> List[Dict[str, Any]]:
    """Get all peers"""
    with get_cursor() as cur:
        cur.execute("SELECT * FROM peers ORDER BY created_at")
        return cur.fetchall()


def get_by_id(peer_id: str) -> Optional[Dict[str, Any]]:
    """Get peer by id (supports partial match with wildcard)"""
    with get_cursor() as cur:
        # First try exact match
        cur.execute("SELECT * FROM peers WHERE id = %s", (peer_id,))
        result = cur.fetchone()
        if result:
            return result
        
        # Try prefix match
        cur.execute("SELECT * FROM peers WHERE id LIKE %s LIMIT 1", (f"{peer_id}:%",))
        return cur.fetchone()


def insert(peer: Dict[str, Any]) -> None:
    """Insert a new peer"""
    with get_cursor() as cur:
        cur.execute(
            """
            INSERT INTO peers (id, name, public_bytes_b64, is_reachable)
            VALUES (%(id)s, %(name)s, %(public_bytes_b64)s, %(is_reachable)s)
            """,
            peer,
        )


def update(
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
    
    with get_cursor() as cur:
        cur.execute(
            f"UPDATE peers SET {', '.join(set_parts)} WHERE id = %(id)s",
            params,
        )


def delete(peer_id: str) -> None:
    """Delete a peer"""
    with get_cursor() as cur:
        cur.execute("DELETE FROM peers WHERE id = %s", (peer_id,))


def search_without_pubkey() -> List[Dict[str, Any]]:
    """Search for peers that don't have a public key"""
    with get_cursor() as cur:
        cur.execute("SELECT * FROM peers WHERE public_bytes_b64 IS NOT NULL")
        return cur.fetchall()
