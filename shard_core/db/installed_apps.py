"""
Database access methods for installed apps
"""
import json
from datetime import datetime
from typing import List, Dict, Any, Optional

from shard_core.db.db_connection import get_cursor


def get_all() -> List[Dict[str, Any]]:
    """Get all installed apps"""
    with get_cursor() as cur:
        cur.execute("SELECT * FROM installed_apps ORDER BY created_at")
        return cur.fetchall()


def get_by_name(app_name: str) -> Optional[Dict[str, Any]]:
    """Get installed app by name"""
    with get_cursor() as cur:
        cur.execute("SELECT * FROM installed_apps WHERE name = %s", (app_name,))
        return cur.fetchone()


def insert(app: Dict[str, Any]) -> None:
    """Insert a new installed app"""
    # Set defaults for optional fields
    if 'access' not in app or app['access'] is None:
        app['access'] = 'private'
    if 'version' not in app or app['version'] is None:
        app['version'] = None
    if 'meta' not in app or app['meta'] is None:
        app['meta'] = None
    
    # Convert meta dict to JSON if present
    if app['meta'] is not None and isinstance(app['meta'], dict):
        app['meta'] = json.dumps(app['meta'])
    
    with get_cursor() as cur:
        cur.execute(
            """
            INSERT INTO installed_apps (name, status, installation_reason, access, last_access, version, meta)
            VALUES (%(name)s, %(status)s, %(installation_reason)s, %(access)s, %(last_access)s, %(version)s, %(meta)s)
            ON CONFLICT (name) DO UPDATE SET
                status = EXCLUDED.status,
                installation_reason = EXCLUDED.installation_reason,
                access = EXCLUDED.access,
                last_access = EXCLUDED.last_access,
                version = EXCLUDED.version,
                meta = EXCLUDED.meta,
                updated_at = CURRENT_TIMESTAMP
            """,
            app,
        )


def update(
    app_name: str,
    *,
    status: Optional[str] = None,
    installation_reason: Optional[str] = None,
    access: Optional[str] = None,
    last_access: Optional[datetime] = None,
    version: Optional[str] = None,
    meta: Optional[Dict[str, Any]] = None
) -> None:
    """Update an installed app with typed parameters"""
    updates = {}
    if status is not None:
        updates['status'] = status
    if installation_reason is not None:
        updates['installation_reason'] = installation_reason
    if access is not None:
        updates['access'] = access
    if last_access is not None:
        updates['last_access'] = last_access
    if version is not None:
        updates['version'] = version
    if meta is not None:
        updates['meta'] = json.dumps(meta) if isinstance(meta, dict) else meta
    
    if not updates:
        return
    
    set_parts = [f"{key} = %({key})s" for key in updates.keys()]
    params = updates.copy()
    params['name'] = app_name
    params['updated_at'] = datetime.utcnow()
    set_parts.append("updated_at = %(updated_at)s")
    
    with get_cursor() as cur:
        cur.execute(
            f"UPDATE installed_apps SET {', '.join(set_parts)} WHERE name = %(name)s",
            params,
        )


def delete(app_name: str) -> None:
    """Delete an installed app"""
    with get_cursor() as cur:
        cur.execute("DELETE FROM installed_apps WHERE name = %s", (app_name,))
