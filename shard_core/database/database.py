import logging

from shard_core.database.connection import db_conn, make_and_open_connection_pool, close_connection_pool
from shard_core.database.migration import migrate
from shard_core.database import kv_store

log = logging.getLogger(__name__)


async def init_database():
    migrate()
    await make_and_open_connection_pool()
    log.info("database initialized")


async def shutdown_database():
    await close_connection_pool()
    log.info("database shut down")


async def get_value(key: str):
    async with db_conn() as conn:
        return await kv_store.get_value(conn, key)


async def set_value(key: str, value):
    async with db_conn() as conn:
        await kv_store.set_value(conn, key, value)


async def remove_value(key: str) -> bool:
    async with db_conn() as conn:
        return await kv_store.remove_value(conn, key)
