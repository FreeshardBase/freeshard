"""One-time migration of TinyDB JSON data to PostgreSQL.

On first startup after switching to Postgres, if the old shard_core_db.json file
exists, this module reads it, inserts all data into the Postgres tables, and renames
the file to shard_core_db.json.backup.
"""

import json
import logging
from datetime import datetime
from pathlib import Path

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

from shard_core.database.connection import db_conn
from shard_core.database.kv_store import _DateTimeEncoder
from shard_core.settings import settings


def _jsonb(value):
    """Create a Jsonb value with datetime-aware JSON encoding."""
    return Jsonb(value, dumps=lambda v: json.dumps(v, cls=_DateTimeEncoder))


log = logging.getLogger(__name__)

# TinyDB serializes datetimes as "{TinyDate}:2023-04-12T02:00:00.002497"
_TINYDATE_PREFIX = "{TinyDate}:"

# Columns that exist in the DB for each table — used to filter out computed fields
_IDENTITY_COLUMNS = {"id", "name", "email", "description", "private_key", "is_default"}
_INSTALLED_APP_COLUMNS = {"name", "installation_reason", "status", "last_access"}
_TERMINAL_COLUMNS = {"id", "name", "icon", "last_connection"}
_PEER_COLUMNS = {"id", "name", "public_bytes_b64", "is_reachable"}


def _parse_tinydate(value):
    """Recursively parse TinyDate strings in a data structure."""
    if isinstance(value, str) and value.startswith(_TINYDATE_PREFIX):
        dt_str = value[len(_TINYDATE_PREFIX) :]
        try:
            return datetime.fromisoformat(dt_str)
        except ValueError:
            return value
    elif isinstance(value, dict):
        return {k: _parse_tinydate(v) for k, v in value.items()}
    elif isinstance(value, list):
        return [_parse_tinydate(v) for v in value]
    return value


def _filter_keys(record: dict, allowed_keys: set) -> dict:
    """Return only the keys that exist in the DB schema."""
    return {k: v for k, v in record.items() if k in allowed_keys}


async def migrate_tinydb_data():
    """Read old TinyDB JSON file and migrate data to Postgres."""
    db_file = Path(settings().path_root) / "core" / "shard_core_db.json"
    if not db_file.exists():
        return

    log.info(f"found TinyDB file at {db_file}, starting migration to Postgres")

    with open(db_file) as f:
        data = json.load(f)

    # Parse all TinyDate strings
    data = _parse_tinydate(data)

    async with db_conn() as conn:
        await _migrate_kv_store(conn, data.get("_default", {}))
        await _migrate_identities(conn, data.get("identities", {}))
        await _migrate_installed_apps(conn, data.get("installed_apps", {}))
        await _migrate_terminals(conn, data.get("terminals", {}))
        await _migrate_peers(conn, data.get("peers", {}))
        await _migrate_backups(conn, data.get("backups", {}))
        await _migrate_tours(conn, data.get("tours", {}))
        await _migrate_app_usage_tracks(conn, data.get("app_usage_track", {}))

    backup_path = db_file.with_suffix(".json.backup")
    db_file.rename(backup_path)
    log.info(f"TinyDB data migrated to Postgres, old file backed up to {backup_path}")


async def _migrate_kv_store(conn: AsyncConnection, records: dict):
    for record in records.values():
        await conn.execute(
            """INSERT INTO kv_store (key, value)
               VALUES (%(key)s, %(value)s)
               ON CONFLICT (key) DO NOTHING""",
            {"key": record["key"], "value": _jsonb(record["value"])},
        )
    log.info(f"migrated {len(records)} kv_store entries")


async def _migrate_identities(conn: AsyncConnection, records: dict):
    for record in records.values():
        filtered = _filter_keys(record, _IDENTITY_COLUMNS)
        await conn.execute(
            """INSERT INTO identities (id, name, email, description, private_key, is_default)
               VALUES (%(id)s, %(name)s, %(email)s, %(description)s, %(private_key)s, %(is_default)s)
               ON CONFLICT (id) DO NOTHING""",
            filtered,
        )
    log.info(f"migrated {len(records)} identities")


async def _migrate_installed_apps(conn: AsyncConnection, records: dict):
    for record in records.values():
        filtered = _filter_keys(record, _INSTALLED_APP_COLUMNS)
        filtered.setdefault("installation_reason", "unknown")
        filtered.setdefault("status", "unknown")
        await conn.execute(
            """INSERT INTO installed_apps (name, installation_reason, status, last_access)
               VALUES (%(name)s, %(installation_reason)s, %(status)s, %(last_access)s)
               ON CONFLICT (name) DO NOTHING""",
            filtered,
        )
    log.info(f"migrated {len(records)} installed apps")


async def _migrate_terminals(conn: AsyncConnection, records: dict):
    for record in records.values():
        filtered = _filter_keys(record, _TERMINAL_COLUMNS)
        filtered.setdefault("icon", "unknown")
        await conn.execute(
            """INSERT INTO terminals (id, name, icon, last_connection)
               VALUES (%(id)s, %(name)s, %(icon)s, %(last_connection)s)
               ON CONFLICT (id) DO NOTHING""",
            filtered,
        )
    log.info(f"migrated {len(records)} terminals")


async def _migrate_peers(conn: AsyncConnection, records: dict):
    for record in records.values():
        filtered = _filter_keys(record, _PEER_COLUMNS)
        await conn.execute(
            """INSERT INTO peers (id, name, public_bytes_b64, is_reachable)
               VALUES (%(id)s, %(name)s, %(public_bytes_b64)s, %(is_reachable)s)
               ON CONFLICT (id) DO NOTHING""",
            filtered,
        )
    log.info(f"migrated {len(records)} peers")


async def _migrate_backups(conn: AsyncConnection, records: dict):
    for record in records.values():
        await conn.execute(
            """INSERT INTO backups (directories, start_time, end_time)
               VALUES (%(directories)s, %(start_time)s, %(end_time)s)""",
            {
                "directories": _jsonb(record.get("directories", [])),
                "start_time": record.get("startTime"),
                "end_time": record.get("endTime"),
            },
        )
    log.info(f"migrated {len(records)} backup reports")


async def _migrate_tours(conn: AsyncConnection, records: dict):
    for record in records.values():
        await conn.execute(
            """INSERT INTO tours (name, status)
               VALUES (%(name)s, %(status)s)
               ON CONFLICT (name) DO NOTHING""",
            record,
        )
    log.info(f"migrated {len(records)} tours")


async def _migrate_app_usage_tracks(conn: AsyncConnection, records: dict):
    for record in records.values():
        await conn.execute(
            """INSERT INTO app_usage_tracks (timestamp, installed_apps)
               VALUES (%(timestamp)s, %(installed_apps)s)""",
            {
                "timestamp": record["timestamp"],
                "installed_apps": _jsonb(record["installed_apps"]),
            },
        )
    log.info(f"migrated {len(records)} app usage tracks")
