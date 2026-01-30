"""
Database module for PostgreSQL connection and initialization
"""
import logging
from contextlib import contextmanager
from typing import Optional

import gconf
import psycopg
from psycopg import Connection
from psycopg.rows import dict_row

log = logging.getLogger(__name__)

_connection: Optional[Connection] = None


def get_connection_string() -> str:
    """Build PostgreSQL connection string from config"""
    db_config = gconf.get("db")
    return (
        f"host={db_config['host']} "
        f"port={db_config['port']} "
        f"dbname={db_config['dbname']} "
        f"user={db_config['user']} "
        f"password={db_config['password']}"
    )


def init_database():
    """Initialize database connection"""
    global _connection
    
    try:
        conninfo = get_connection_string()
        _connection = psycopg.connect(conninfo, autocommit=True, row_factory=dict_row)
        log.info("Database connection established")
    except Exception as e:
        log.error(f"Failed to connect to database: {e}")
        raise


def get_connection() -> Connection:
    """Get the global database connection"""
    if _connection is None:
        init_database()
    return _connection


@contextmanager
def get_cursor():
    """Get a database cursor with dict row factory"""
    conn = get_connection()
    with conn.cursor() as cur:
        yield cur


def close_connection():
    """Close the database connection"""
    global _connection
    if _connection:
        _connection.close()
        _connection = None
        log.info("Database connection closed")
