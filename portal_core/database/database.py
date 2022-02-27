import logging
from contextlib import contextmanager
from pathlib import Path

import gconf
from tinydb import TinyDB, Query, JSONStorage
from tinydb.table import Table
from tinydb_serialization import SerializationMiddleware
from tinydb_serialization.serializers import DateTimeSerializer

log = logging.getLogger(__name__)


def init_database():
	file = Path(gconf.get('database.filename'))
	if file.is_dir():
		raise Exception(f'{file} is a directory, should be a file or not existing')
	if not file.exists():
		file.parent.mkdir(parents=True, exist_ok=True)
		file.touch()
		log.info(f'initialized database at {file}')
	else:
		log.debug(f'database already exists at {file}')


@contextmanager
def get_db() -> TinyDB:
	serialization = SerializationMiddleware(JSONStorage)
	serialization.register_serializer(DateTimeSerializer(), 'TinyDate')

	with TinyDB(gconf.get('database.filename'), storage=serialization, sort_keys=True, indent=2) as db_:
		yield db_


@contextmanager
def apps_table() -> Table:
	with get_db() as db:
		yield db.table('apps')


@contextmanager
def identities_table() -> Table:
	with get_db() as db:
		yield db.table('identities')


@contextmanager
def terminals_table() -> Table:
	with get_db() as db:
		yield db.table('terminals')


@contextmanager
def peers_table() -> Table:
	with get_db() as db:
		yield db.table('peers')


@contextmanager
def tours_table() -> Table:
	with get_db() as db:
		yield db.table('tours')


def get_value(key: str):
	with get_db() as db:
		if result := db.get(Query().key == key):
			return result['value']
		else:
			raise KeyError(key)


def set_value(key: str, value):
	with get_db() as db:
		db.upsert({
			'key': key,
			'value': value,
		}, Query().key == key)


def remove_value(key: str):
	with get_db() as db:
		removed_ids = db.remove(Query().key == key)
	return len(removed_ids) > 0
