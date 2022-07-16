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
