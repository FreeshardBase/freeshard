from contextlib import contextmanager
from pathlib import Path

import gconf
from tinydb import TinyDB


def init_database():
	file = Path(gconf.get('database.filename'))
	if file.is_dir():
		raise Exception(f'{file} is a directory, should be a file or not existing')
	if not file.exists():
		file.parent.mkdir(parents=True, exist_ok=True)
		file.touch()


@contextmanager
def get_db() -> TinyDB:
	with TinyDB(gconf.get('database.filename'), sort_keys=True, indent=2) as db_:
		yield db_
