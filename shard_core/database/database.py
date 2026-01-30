"""
Database module - Compatibility layer for PostgreSQL
This module maintains the old API for backward compatibility
while delegating to the new PostgreSQL implementation.
"""
import logging

from shard_core.database import db_connection, db_methods

log = logging.getLogger(__name__)


def init_database():
    """Initialize database connection"""
    db_connection.init_database()
    log.info("Database initialized")


# Re-export methods for backward compatibility
get_value = db_methods.get_value
set_value = db_methods.set_value
remove_value = db_methods.remove_value
