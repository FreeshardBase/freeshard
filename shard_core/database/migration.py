import logging
from pathlib import Path

import psycopg
from yoyo import get_backend, read_migrations

from shard_core.settings import settings

log = logging.getLogger(__name__)


def migrate():
    db = settings().db
    conn_string = (
        f"postgresql+psycopg://{db.user}:{db.password}@{db.host}:{db.port}/{db.dbname}"
    )
    try:
        backend = get_backend(conn_string)
    except psycopg.OperationalError as e:
        log.exception(f"failed to connect to {conn_string}")
        raise e
    migrations_path = Path.cwd() / "migrations"
    migrations = read_migrations(str(migrations_path))
    log.debug(f"reading migrations: {migrations}")
    with backend.lock():
        backend.apply_migrations(backend.to_apply(migrations))
    log.info("database migrations applied")
