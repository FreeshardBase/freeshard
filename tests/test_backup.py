from pathlib import Path
from zipfile import ZipFile


def test_backup(api_client, tmp_path, postgres):
	root_ = tmp_path / 'path_root'
	backup_ = tmp_path / 'backup'
	file_not_included = Path('not included')
	(root_ / file_not_included).touch()

	zip_path = tmp_path / 'backup.zip'

	with api_client.get('protected/backup/export', stream=True) as r:
		r.raise_for_status()
		with open(zip_path, 'wb') as f:
			for chunk in r.iter_content(chunk_size=8192):
				f.write(chunk)

	zip_file = ZipFile(zip_path)
	zip_file.extractall(backup_)

	files_in_root = {p.relative_to(root_) for p in Path(root_).rglob('*') if p.is_file()}
	files_in_backup = {p.relative_to(backup_) for p in Path(backup_).rglob('*') if p.is_file()}

	assert file_not_included in files_in_root - files_in_backup
	assert Path('core/portal_core_db.json') in files_in_backup
	assert files_in_backup - files_in_root == set()
