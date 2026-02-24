import logging

log = logging.getLogger(__name__)


async def migrate():
    # The old TinyDB "apps" -> "installed_apps" table migration is no longer needed
    # since we now use PostgreSQL with yoyo migrations for schema management.
    log.debug("no legacy migration needed")
