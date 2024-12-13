import logging
from pathlib import Path

import gconf
from sqlmodel import SQLModel, create_engine, Session

log = logging.getLogger(__name__)

_engine = None


def engine():
    global _engine
    if _engine is None:
        log.info(f'creating database engine at {_sqlite_url()}')
        _engine = create_engine(_sqlite_url())
    return _engine

def session():
    return Session(engine())

def create_db_and_tables():
    log.info(f'creating database and tables at {_sqlite_url()}')
    Path(_sqlite_file()).parent.mkdir(parents=True, exist_ok=True)
    SQLModel.metadata.create_all(engine())

def _sqlite_file():
    return f'{gconf.get('path_root')}/{gconf.get('db.sqlite_file')}'


def _sqlite_url():
    sqlite_url = f"sqlite:///{_sqlite_file()}"
    return sqlite_url
