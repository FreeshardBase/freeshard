from pathlib import Path
from typing import Tuple, Set
from zipfile import ZipFile


def test_backup(api_client, tmp_path, postgres):
	zip_path = tmp_path / 'backup.zip'

	with api_client.get('protected/backup/export', stream=True) as r:
		r.raise_for_status()
		with open(zip_path, 'wb') as f:
			for chunk in r.iter_content(chunk_size=8192):
				f.write(chunk)

	zip_file = ZipFile(zip_path)
	zip_file.extractall(tmp_path / 'backup')

	only_left, only_right = _filenames_compare(tmp_path / 'path_root', tmp_path / 'backup')
	assert len(only_left) == 0
	assert len(only_right) == 1

	right_file = tmp_path / 'backup' / only_right.pop()
	assert right_file.name == 'postgres_dump.sql'
	assert 'PostgreSQL database cluster dump' in right_file.read_text()


def _filenames_compare(dir_left, dir_right) -> Tuple[Set, Set]:
	files_left = {p.relative_to(dir_left) for p in Path(dir_left).rglob('*') if p.is_file()}
	files_right = {p.relative_to(dir_right) for p in Path(dir_right).rglob('*') if p.is_file()}
	only_left = files_left - files_right
	only_right = files_right - files_left
	return only_left, only_right
