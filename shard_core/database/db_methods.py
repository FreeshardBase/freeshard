"""
Database access methods for all tables
"""
import json
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional

from shard_core.database.db_connection import get_cursor

log = logging.getLogger(__name__)


# ===== Identity methods =====

def get_all_identities() -> List[Dict[str, Any]]:
    """Get all identities"""
    with get_cursor() as cur:
        cur.execute("SELECT * FROM identities ORDER BY created_at")
        return cur.fetchall()


def get_identity_by_id(identity_id: str) -> Optional[Dict[str, Any]]:
    """Get identity by id"""
    with get_cursor() as cur:
        cur.execute("SELECT * FROM identities WHERE id = %s", (identity_id,))
        return cur.fetchone()


def get_default_identity() -> Optional[Dict[str, Any]]:
    """Get the default identity"""
    with get_cursor() as cur:
        cur.execute("SELECT * FROM identities WHERE is_default = TRUE LIMIT 1")
        return cur.fetchone()


def insert_identity(identity: Dict[str, Any]) -> None:
    """Insert a new identity"""
    with get_cursor() as cur:
        cur.execute(
            """
            INSERT INTO identities (id, name, email, description, private_key, is_default)
            VALUES (%(id)s, %(name)s, %(email)s, %(description)s, %(private_key)s, %(is_default)s)
            """,
            identity,
        )


def update_identity(identity_id: str, updates: Dict[str, Any]) -> None:
    """Update an identity"""
    if not updates:
        return
    
    # Build SET clause dynamically
    set_parts = []
    params = {}
    for key, value in updates.items():
        if key != 'id':  # Don't update the ID
            set_parts.append(f"{key} = %({key})s")
            params[key] = value
    
    if not set_parts:
        return
    
    params['id'] = identity_id
    params['updated_at'] = datetime.utcnow()
    set_parts.append("updated_at = %(updated_at)s")
    
    with get_cursor() as cur:
        cur.execute(
            f"UPDATE identities SET {', '.join(set_parts)} WHERE id = %(id)s",
            params,
        )


def delete_identity(identity_id: str) -> None:
    """Delete an identity"""
    with get_cursor() as cur:
        cur.execute("DELETE FROM identities WHERE id = %s", (identity_id,))


def count_identities() -> int:
    """Count all identities"""
    with get_cursor() as cur:
        cur.execute("SELECT COUNT(*) as count FROM identities")
        return cur.fetchone()['count']


# ===== Terminal methods =====

def get_all_terminals() -> List[Dict[str, Any]]:
    """Get all terminals"""
    with get_cursor() as cur:
        cur.execute("SELECT * FROM terminals ORDER BY last_connection DESC")
        return cur.fetchall()


def get_terminal_by_id(terminal_id: str) -> Optional[Dict[str, Any]]:
    """Get terminal by id"""
    with get_cursor() as cur:
        cur.execute("SELECT * FROM terminals WHERE id = %s", (terminal_id,))
        return cur.fetchone()


def insert_terminal(terminal: Dict[str, Any]) -> None:
    """Insert a new terminal"""
    with get_cursor() as cur:
        cur.execute(
            """
            INSERT INTO terminals (id, name, icon, last_connection)
            VALUES (%(id)s, %(name)s, %(icon)s, %(last_connection)s)
            """,
            terminal,
        )


def update_terminal(terminal_id: str, updates: Dict[str, Any]) -> None:
    """Update a terminal"""
    if not updates:
        return
    
    set_parts = []
    params = {}
    for key, value in updates.items():
        if key != 'id':
            set_parts.append(f"{key} = %({key})s")
            params[key] = value
    
    if not set_parts:
        return
    
    params['id'] = terminal_id
    params['updated_at'] = datetime.utcnow()
    set_parts.append("updated_at = %(updated_at)s")
    
    with get_cursor() as cur:
        cur.execute(
            f"UPDATE terminals SET {', '.join(set_parts)} WHERE id = %(id)s",
            params,
        )


def delete_terminal(terminal_id: str) -> None:
    """Delete a terminal"""
    with get_cursor() as cur:
        cur.execute("DELETE FROM terminals WHERE id = %s", (terminal_id,))


def count_terminals() -> int:
    """Count all terminals"""
    with get_cursor() as cur:
        cur.execute("SELECT COUNT(*) as count FROM terminals")
        return cur.fetchone()['count']


# ===== Peer methods =====

def get_all_peers() -> List[Dict[str, Any]]:
    """Get all peers"""
    with get_cursor() as cur:
        cur.execute("SELECT * FROM peers ORDER BY created_at")
        return cur.fetchall()


def get_peer_by_id(peer_id: str) -> Optional[Dict[str, Any]]:
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


def insert_peer(peer: Dict[str, Any]) -> None:
    """Insert a new peer"""
    with get_cursor() as cur:
        cur.execute(
            """
            INSERT INTO peers (id, name, public_bytes_b64, is_reachable)
            VALUES (%(id)s, %(name)s, %(public_bytes_b64)s, %(is_reachable)s)
            """,
            peer,
        )


def update_peer(peer_id: str, updates: Dict[str, Any]) -> None:
    """Update a peer"""
    if not updates:
        return
    
    set_parts = []
    params = {}
    for key, value in updates.items():
        if key != 'id':
            set_parts.append(f"{key} = %({key})s")
            params[key] = value
    
    if not set_parts:
        return
    
    params['id'] = peer_id
    params['updated_at'] = datetime.utcnow()
    set_parts.append("updated_at = %(updated_at)s")
    
    with get_cursor() as cur:
        cur.execute(
            f"UPDATE peers SET {', '.join(set_parts)} WHERE id = %(id)s",
            params,
        )


def delete_peer(peer_id: str) -> None:
    """Delete a peer"""
    with get_cursor() as cur:
        cur.execute("DELETE FROM peers WHERE id = %s", (peer_id,))


def search_peers_without_pubkey() -> List[Dict[str, Any]]:
    """Search for peers that don't have a public key"""
    with get_cursor() as cur:
        cur.execute("SELECT * FROM peers WHERE public_bytes_b64 IS NOT NULL")
        return cur.fetchall()


# ===== Installed Apps methods =====

def get_all_installed_apps() -> List[Dict[str, Any]]:
    """Get all installed apps"""
    with get_cursor() as cur:
        cur.execute("SELECT * FROM installed_apps ORDER BY created_at")
        return cur.fetchall()


def get_installed_app_by_name(app_name: str) -> Optional[Dict[str, Any]]:
    """Get installed app by name"""
    with get_cursor() as cur:
        cur.execute("SELECT * FROM installed_apps WHERE name = %s", (app_name,))
        return cur.fetchone()


def insert_installed_app(app: Dict[str, Any]) -> None:
    """Insert a new installed app"""
    # Convert meta dict to JSON if present
    if 'meta' in app and app['meta'] is not None:
        app['meta'] = json.dumps(app['meta']) if isinstance(app['meta'], dict) else app['meta']
    
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


def update_installed_app(app_name: str, updates: Dict[str, Any]) -> None:
    """Update an installed app"""
    if not updates:
        return
    
    # Convert meta dict to JSON if present
    if 'meta' in updates and updates['meta'] is not None:
        updates['meta'] = json.dumps(updates['meta']) if isinstance(updates['meta'], dict) else updates['meta']
    
    set_parts = []
    params = {}
    for key, value in updates.items():
        if key != 'name':
            set_parts.append(f"{key} = %({key})s")
            params[key] = value
    
    if not set_parts:
        return
    
    params['name'] = app_name
    params['updated_at'] = datetime.utcnow()
    set_parts.append("updated_at = %(updated_at)s")
    
    with get_cursor() as cur:
        cur.execute(
            f"UPDATE installed_apps SET {', '.join(set_parts)} WHERE name = %(name)s",
            params,
        )


def delete_installed_app(app_name: str) -> None:
    """Delete an installed app"""
    with get_cursor() as cur:
        cur.execute("DELETE FROM installed_apps WHERE name = %s", (app_name,))


# ===== Tours methods =====

def get_all_tours() -> List[Dict[str, Any]]:
    """Get all tours"""
    with get_cursor() as cur:
        cur.execute("SELECT * FROM tours ORDER BY created_at")
        return cur.fetchall()


def get_tour_by_id(tour_id: str) -> Optional[Dict[str, Any]]:
    """Get tour by id"""
    with get_cursor() as cur:
        cur.execute("SELECT * FROM tours WHERE id = %s", (tour_id,))
        return cur.fetchone()


def insert_tour(tour: Dict[str, Any]) -> None:
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


def update_tour(tour_id: str, updates: Dict[str, Any]) -> None:
    """Update a tour"""
    if not updates:
        return
    
    set_parts = []
    params = {}
    for key, value in updates.items():
        if key != 'id':
            set_parts.append(f"{key} = %({key})s")
            params[key] = value
    
    if not set_parts:
        return
    
    params['id'] = tour_id
    params['updated_at'] = datetime.utcnow()
    set_parts.append("updated_at = %(updated_at)s")
    
    with get_cursor() as cur:
        cur.execute(
            f"UPDATE tours SET {', '.join(set_parts)} WHERE id = %(id)s",
            params,
        )


def delete_tour(tour_id: str) -> None:
    """Delete a tour"""
    with get_cursor() as cur:
        cur.execute("DELETE FROM tours WHERE id = %s", (tour_id,))


def count_tours() -> int:
    """Count all tours"""
    with get_cursor() as cur:
        cur.execute("SELECT COUNT(*) as count FROM tours")
        return cur.fetchone()['count']


def delete_all_tours() -> None:
    """Delete all tours"""
    with get_cursor() as cur:
        cur.execute("DELETE FROM tours")


# ===== App Usage Track methods =====

def get_all_app_usage_tracks() -> List[Dict[str, Any]]:
    """Get all app usage tracks"""
    with get_cursor() as cur:
        cur.execute("SELECT * FROM app_usage_track ORDER BY timestamp DESC")
        return cur.fetchall()


def insert_app_usage_track(track: Dict[str, Any]) -> None:
    """Insert a new app usage track"""
    # Convert installed_apps list to JSON
    if 'installed_apps' in track:
        track['installed_apps'] = json.dumps(track['installed_apps']) if isinstance(track['installed_apps'], list) else track['installed_apps']
    
    with get_cursor() as cur:
        cur.execute(
            """
            INSERT INTO app_usage_track (timestamp, installed_apps)
            VALUES (%(timestamp)s, %(installed_apps)s)
            """,
            track,
        )


# ===== Key-Value methods =====

def get_value(key: str) -> Any:
    """Get value by key"""
    with get_cursor() as cur:
        cur.execute("SELECT value FROM key_value WHERE key = %s", (key,))
        result = cur.fetchone()
        if result:
            return result['value']
        else:
            raise KeyError(key)


def set_value(key: str, value: Any) -> None:
    """Set or update a key-value pair"""
    # Convert value to JSON
    json_value = json.dumps(value)
    
    with get_cursor() as cur:
        cur.execute(
            """
            INSERT INTO key_value (key, value)
            VALUES (%s, %s)
            ON CONFLICT (key) DO UPDATE SET
                value = EXCLUDED.value,
                updated_at = CURRENT_TIMESTAMP
            """,
            (key, json_value),
        )


def remove_value(key: str) -> bool:
    """Remove a key-value pair, returns True if removed"""
    with get_cursor() as cur:
        cur.execute("DELETE FROM key_value WHERE key = %s RETURNING key", (key,))
        return cur.fetchone() is not None


# ===== Utility methods =====

def truncate_all_tables() -> None:
    """Truncate all tables - useful for tests"""
    with get_cursor() as cur:
        cur.execute(
            """
            TRUNCATE TABLE 
                identities, 
                terminals, 
                peers, 
                installed_apps, 
                tours, 
                app_usage_track, 
                key_value
            RESTART IDENTITY CASCADE
            """
        )
    log.debug("All tables truncated")
