from pathlib import Path
from typing import BinaryIO

import gconf


def assets_path() -> Path:
	return Path(gconf.get('path_root')) / 'core' / 'assets'


def avatars_path() -> Path:
	return assets_path() / 'avatars'


def put_asset(file: bytes, path: Path, overwrite: bool = False):
	if path.is_absolute():
		raise ValueError('path must be relative')
	effective_path = assets_path() / path
	if effective_path.exists() and not overwrite:
		raise FileExistsError()
	effective_path.parent.mkdir(parents=True, exist_ok=True)
	with open(effective_path, 'wb') as f:
		f.write(file)


def get_asset(path: Path) -> BinaryIO:
	if path.is_absolute():
		raise ValueError('path must be relative')
	effective_path = assets_path() / path
	if not effective_path.exists():
		raise FileNotFoundError()
	return open(effective_path, 'rb')


def delete_asset(path: Path):
	if path.is_absolute():
		raise ValueError('path must be relative')
	effective_path = assets_path() / path
	if not effective_path.exists():
		raise FileNotFoundError()
	effective_path.unlink()
