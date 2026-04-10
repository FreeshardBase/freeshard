import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from psycopg import AsyncConnection
from psycopg.conninfo import make_conninfo
from psycopg_pool import AsyncConnectionPool

from shard_core.settings import settings

log = logging.getLogger(__name__)

# noinspection PyTypeChecker
connection_pool: AsyncConnectionPool = None


async def make_and_open_connection_pool():
    global connection_pool
    db = settings().db
    connection_pool = AsyncConnectionPool(
        conninfo=make_conninfo(
            host=db.host,
            port=db.port,
            dbname=db.dbname,
            user=db.user,
            password=db.password,
        ),
        open=False,
    )
    await connection_pool.open()
    log.info("database connection pool opened")


async def close_connection_pool():
    global connection_pool
    if connection_pool:
        await connection_pool.close()
        connection_pool = None
        log.info("database connection pool closed")


def get_connection_pool() -> AsyncConnectionPool:
    if connection_pool is None:
        raise RuntimeError(
            "Database pool not initialized. Call make_and_open_connection_pool() first."
        )
    return connection_pool


@asynccontextmanager
async def db_conn() -> AsyncGenerator[AsyncConnection, None]:
    async with get_connection_pool().connection() as conn:
        yield conn
