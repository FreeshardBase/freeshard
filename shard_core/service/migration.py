import logging

log = logging.getLogger(__name__)


async def migrate():
    """
    Migration from TinyDB to PostgreSQL.
    This function is now a no-op since we're using PostgreSQL.
    The actual schema migrations are handled by yoyo-migrations.
    """
    log.debug("no migration needed - already using PostgreSQL")
    return
