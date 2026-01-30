"""
Utility methods for database operations
"""
import logging

from shard_core.db.db_connection import get_cursor

log = logging.getLogger(__name__)


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
                key_value,
                backup_reports
            RESTART IDENTITY CASCADE
            """
        )
    log.debug("All tables truncated")
