"""
Database access methods for identities
"""
from datetime import datetime
from typing import List, Optional

from psycopg import AsyncConnection
from psycopg.rows import class_row

from shard_core.data_model.identity import Identity


async def get_all(conn: AsyncConnection) -> List[Identity]:
    """Get all identities"""
    async with conn.cursor(row_factory=class_row(Identity)) as cur:
        await cur.execute("SELECT * FROM identities ORDER BY created_at")
        return await cur.fetchall()


async def get_by_id(conn: AsyncConnection, identity_id: str) -> Optional[Identity]:
    """Get identity by id"""
    async with conn.cursor(row_factory=class_row(Identity)) as cur:
        await cur.execute("SELECT * FROM identities WHERE id = %s", (identity_id,))
        return await cur.fetchone()


async def get_default(conn: AsyncConnection) -> Optional[Identity]:
    """Get the default identity"""
    async with conn.cursor(row_factory=class_row(Identity)) as cur:
        await cur.execute("SELECT * FROM identities WHERE is_default = TRUE LIMIT 1")
        return await cur.fetchone()


async def insert(conn: AsyncConnection, identity: Identity) -> None:
    """Insert a new identity"""
    async with conn.cursor() as cur:
        await cur.execute(
            """
            INSERT INTO identities (id, name, email, description, private_key, is_default)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (identity.id, identity.name, identity.email, identity.description, identity.private_key, identity.is_default),
        )


async def update(
    conn: AsyncConnection,
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
    
    async with conn.cursor() as cur:
        await cur.execute(
            f"UPDATE identities SET {', '.join(set_parts)} WHERE id = %(id)s",
            params,
        )


async def delete(conn: AsyncConnection, identity_id: str) -> None:
    """Delete an identity"""
    async with conn.cursor() as cur:
        await cur.execute("DELETE FROM identities WHERE id = %s", (identity_id,))


async def count(conn: AsyncConnection) -> int:
    """Count all identities"""
    async with conn.cursor() as cur:
        await cur.execute("SELECT COUNT(*) as count FROM identities")
        result = await cur.fetchone()
        return result[0]
