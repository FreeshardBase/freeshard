from pathlib import Path
from zipfile import ZipFile

from httpx import AsyncClient


async def test_backup(api_client: AsyncClient, tmp_path, postgres):
	root_ = tmp_path / 'path_root'
	backup_ = tmp_path / 'backup'
	file_not_included = Path('not included')
	(root_ / file_not_included).touch()

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
