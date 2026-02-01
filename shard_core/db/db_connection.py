from contextlib import asynccontextmanager
from typing import AsyncGenerator
from psycopg import AsyncConnection
from psycopg.conninfo import make_conninfo
from psycopg_pool import AsyncConnectionPool

import gconf

# noinspection PyTypeChecker
connection_pool: AsyncConnectionPool = None


async def make_and_open_connection_pool():
    global connection_pool
    connection_pool = AsyncConnectionPool(
        conninfo=make_conninfo(**gconf.get("db")),
        open=False,
    )
    await connection_pool.open()
    return connection_pool


async def close_connection_pool() -> None:
    global connection_pool
    await connection_pool.close()


def get_connection_pool() -> AsyncConnectionPool:
    if connection_pool is None:
        raise RuntimeError("No connection pool available")
    return connection_pool


@asynccontextmanager
async def db_conn() -> AsyncGenerator[AsyncConnection, None]:
    db_pool = get_connection_pool()
    async with db_pool.connection() as conn:
        yield conn
