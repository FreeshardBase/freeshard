from pathlib import Path
from zipfile import ZipFile

from httpx import AsyncClient


async def test_backup(api_client: AsyncClient, tmp_path):
	root_ = tmp_path / 'path_root'
	backup_ = tmp_path / 'backup'
	file_not_included = Path('not included')
	(root_ / file_not_included).touch()
	user_data_path = 'user_data/app_data/user_data.json'
	user_data_file = root_ / user_data_path
	user_data_file.parent.mkdir(parents=True)
	user_data_file.write_text('{"foo": "bar"}')

	zip_path = tmp_path / 'backup.zip'

	async with api_client.stream('GET', 'protected/backup/export') as response:  # type: AsyncIterator[httpx.Response]
		with open(zip_path, 'wb') as f:
			async for chunk in response.aiter_bytes():
				f.write(chunk)

	zip_file = ZipFile(zip_path)
	zip_file.extractall(backup_)

	files_in_root = {p.relative_to(root_) for p in Path(root_).rglob('*') if p.is_file()}
	files_in_backup = {p.relative_to(backup_) for p in Path(backup_).rglob('*') if p.is_file()}

	assert file_not_included in files_in_root - files_in_backup
	assert Path('core/portal_core_db.json') in files_in_backup
	assert files_in_backup - files_in_root == set()

	db_from_backup = (Path(backup_) / 'core' / 'portal_core_db.json').read_text()
	db_from_root = (Path(root_) / 'core' / 'portal_core_db.json').read_text()
	assert db_from_backup == db_from_root
	user_data_from_backup = (Path(backup_) / user_data_path).read_text()
	user_data_from_root = (Path(root_) / user_data_path).read_text()
	assert user_data_from_backup == user_data_from_root
