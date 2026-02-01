"""
Utility methods for database operations
"""
import logging

from psycopg import AsyncConnection

log = logging.getLogger(__name__)


async def truncate_all_tables(conn: AsyncConnection) -> None:
    """Truncate all tables - useful for tests"""
    async with conn.cursor() as cur:
        await cur.execute(
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
