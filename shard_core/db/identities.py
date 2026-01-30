"""
Database access methods for identities
"""
from datetime import datetime
from typing import List, Dict, Any, Optional

from shard_core.db.db_connection import get_cursor


def get_all() -> List[Dict[str, Any]]:
    """Get all identities"""
    with get_cursor() as cur:
        cur.execute("SELECT * FROM identities ORDER BY created_at")
        return cur.fetchall()


def get_by_id(identity_id: str) -> Optional[Dict[str, Any]]:
    """Get identity by id"""
    with get_cursor() as cur:
        cur.execute("SELECT * FROM identities WHERE id = %s", (identity_id,))
        return cur.fetchone()


def get_default() -> Optional[Dict[str, Any]]:
    """Get the default identity"""
    with get_cursor() as cur:
        cur.execute("SELECT * FROM identities WHERE is_default = TRUE LIMIT 1")
        return cur.fetchone()


def insert(identity: Dict[str, Any]) -> None:
    """Insert a new identity"""
    with get_cursor() as cur:
        cur.execute(
            """
            INSERT INTO identities (id, name, email, description, private_key, is_default)
            VALUES (%(id)s, %(name)s, %(email)s, %(description)s, %(private_key)s, %(is_default)s)
            """,
            identity,
        )


def update(
    identity_id: str,
    *,
    name: Optional[str] = None,
    email: Optional[str] = None,
    description: Optional[str] = None,
    private_key: Optional[str] = None,
    is_default: Optional[bool] = None
) -> None:
    """Update an identity with typed parameters"""
    updates = {}
    if name is not None:
        updates['name'] = name
    if email is not None:
        updates['email'] = email
    if description is not None:
        updates['description'] = description
    if private_key is not None:
        updates['private_key'] = private_key
    if is_default is not None:
        updates['is_default'] = is_default
    
    if not updates:
        return
    
    # Build SET clause
    set_parts = [f"{key} = %({key})s" for key in updates.keys()]
    params = updates.copy()
    params['id'] = identity_id
    params['updated_at'] = datetime.utcnow()
    set_parts.append("updated_at = %(updated_at)s")
    
    with get_cursor() as cur:
        cur.execute(
            f"UPDATE identities SET {', '.join(set_parts)} WHERE id = %(id)s",
            params,
        )


def delete(identity_id: str) -> None:
    """Delete an identity"""
    with get_cursor() as cur:
        cur.execute("DELETE FROM identities WHERE id = %s", (identity_id,))


def count() -> int:
    """Count all identities"""
    with get_cursor() as cur:
        cur.execute("SELECT COUNT(*) as count FROM identities")
        return cur.fetchone()['count']
