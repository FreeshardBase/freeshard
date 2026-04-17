"""Database initialization and convenience wrappers.

The main database access pattern is:
    async with db_conn() as conn:
        await some_db_module.some_function(conn, ...)

This module provides init/shutdown lifecycle functions and convenience wrappers
for the kv_store that handle connection management internally (for callers that
only need a single kv operation).
"""

import logging

from shard_core.database.connection import (
    db_conn,
    make_and_open_connection_pool,
    close_connection_pool,
)
from shard_core.database.migration import migrate
from shard_core.database.tinydb_migration import migrate_tinydb_data
from shard_core.database import kv_store

log = logging.getLogger(__name__)


async def init_database():
    """Run migrations and open the connection pool.

    Call this once during app startup, before serving requests.
    """
    migrate()
    await make_and_open_connection_pool()
    await migrate_tinydb_data()
    log.info("database initialized")


async def shutdown_database():
    """Close the connection pool. Call during app shutdown."""
    await close_connection_pool()
    log.info("database shut down")


# Convenience wrappers for kv_store (used by callers that don't need a conn for anything else)
async def get_value(key: str):
    async with db_conn() as conn:
        return await kv_store.get_value(conn, key)


async def set_value(key: str, value):
    async with db_conn() as conn:
        await kv_store.set_value(conn, key, value)


async def remove_value(key: str) -> bool:
    async with db_conn() as conn:
        return await kv_store.remove_value(conn, key)
