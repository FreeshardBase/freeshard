import logging

log = logging.getLogger(__name__)


async def migrate():
    """Legacy TinyDB table migration — no longer needed with Postgres.

    The old TinyDB "apps" → "installed_apps" table rename is handled by
    tinydb_migration.py which reads the entire JSON file on first startup.
    """
    log.debug("no legacy migration needed (using Postgres)")
