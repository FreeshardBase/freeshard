import logging
from contextlib import asynccontextmanager

import gconf
from psycopg_pool import AsyncConnectionPool

log = logging.getLogger(__name__)

_pool: AsyncConnectionPool | None = None


async def make_and_open_connection_pool():
    global _pool
    db = gconf.get("db")
    conninfo = f"host={db['host']} port={db['port']} dbname={db['dbname']} user={db['user']} password={db['password']}"
    _pool = AsyncConnectionPool(conninfo=conninfo, min_size=2, max_size=10, open=False)
    await _pool.open()
    log.debug("opened connection pool")


async def close_connection_pool():
    global _pool
    if _pool:
        await _pool.close()
        _pool = None
        log.debug("closed connection pool")


@asynccontextmanager
async def db_conn():
    async with _pool.connection() as conn:
        yield conn
