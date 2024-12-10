import logging

import gconf
from sqlmodel import SQLModel, create_engine, Session

log = logging.getLogger(__name__)

_engine = None


def engine():
    global _engine
    if _engine is None:
        _engine = create_engine(_sqlite_url())
    return _engine

def session():
    return Session(engine())

def create_db_and_tables():
    SQLModel.metadata.create_all(engine())
    log.info('created database and tables')


def _sqlite_url():
    sqlite_file_name = f'{gconf.get('path_root')}/{gconf.get('db.sqlite_file')}'
    sqlite_url = f"sqlite:///{sqlite_file_name}"
    return sqlite_url
