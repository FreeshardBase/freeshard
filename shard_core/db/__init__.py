"""
Database module - re-exports all database access methods
"""
# Import all modules for easy access
from shard_core.db import (
    identities,
    terminals,
    peers,
    installed_apps,
    tours,
    app_usage_track,
    key_value,
    backup_reports,
    util,
    db_connection,
    migration
)

# Re-export commonly used items
from shard_core.db.db_connection import init_database, get_connection, close_connection
from shard_core.db.migration import migrate

__all__ = [
    'identities',
    'terminals',
    'peers',
    'installed_apps',
    'tours',
    'app_usage_track',
    'key_value',
    'backup_reports',
    'util',
    'db_connection',
    'migration',
    'init_database',
    'get_connection',
    'close_connection',
    'migrate',
]
