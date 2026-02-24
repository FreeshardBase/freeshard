import logging
from pathlib import Path

import gconf
import psycopg
from yoyo import get_backend
from yoyo import read_migrations

log = logging.getLogger(__name__)


def migrate():
    db = gconf.get("db")
    conn_string = f"postgresql+psycopg://{db['user']}:{db['password']}@{db['host']}:{db['port']}/{db['dbname']}"
    try:
        backend = get_backend(conn_string)
    except psycopg.OperationalError as e:
        log.exception(f"failed to connect to {conn_string}", e)
        raise e
    migrations_path = Path.cwd() / "migrations"
    migrations = read_migrations(str(migrations_path))
    log.debug(f"Reading migrations: {migrations}")
    with backend.lock():
        backend.apply_migrations(backend.to_apply(migrations))
    log.debug("Migration applied")
