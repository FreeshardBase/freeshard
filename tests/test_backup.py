from pathlib import Path
from zipfile import ZipFile


def test_backup(api_client, tmp_path):
	zip_path = tmp_path / 'backup.zip'

	with api_client.get('protected/backup/export', stream=True) as r:
		r.raise_for_status()
		with open(zip_path, 'wb') as f:
			for chunk in r.iter_content(chunk_size=8192):
				f.write(chunk)

	zip_file = ZipFile(zip_path)
	zip_file.extractall(tmp_path / 'backup')

	assert _filenames_match(tmp_path / 'path_root', tmp_path / 'backup')


def _filenames_match(dir1, dir2) -> bool:
	files1 = {p.relative_to(dir1) for p in Path(dir1).rglob('*') if p.is_file()}
	files2 = {p.relative_to(dir2) for p in Path(dir2).rglob('*') if p.is_file()}
	return files1 == files2
