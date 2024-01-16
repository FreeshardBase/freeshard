import json
import shutil
from pathlib import Path

import pytest

from portal_core.model.app_meta import Status
from tests.util import retry_async


@pytest.fixture
def init_db_file(tmp_path):
	init_db_file = Path(__file__).parent / 'init_db.json'
	dest = tmp_path / 'path_root' / 'core' / 'portal_core_db.json'
	dest.parent.mkdir(parents=True, exist_ok=True)
	dest.touch()
	shutil.copy(init_db_file, dest)


async def test_migration(init_db_file, api_client, tmp_path):
	response = (await api_client.get('protected/apps')).json()
	assert len(response) == 2
	assert any(app['name'] == 'filebrowser' for app in response)
	assert any(app['name'] == 'mock_app' for app in response)

	async def assert_status_down():
		assert all(app['status'] == Status.STOPPED for app in response)

	await retry_async(assert_status_down)

	with open(tmp_path / 'path_root' / 'core' / 'portal_core_db.json') as f:
		db = json.load(f)
	assert 'apps' not in db


@pytest.fixture
def init_db_file_nonexisting_app(tmp_path):
	init_db_file = Path(__file__).parent / 'init_db_nonexisting_app.json'
	dest = tmp_path / 'path_root' / 'core' / 'portal_core_db.json'
	dest.parent.mkdir(parents=True, exist_ok=True)
	dest.touch()
	shutil.copy(init_db_file, dest)


async def test_migration_nonexisting_app(
		init_db_file_nonexisting_app, api_client, tmp_path):
	response = (await api_client.get('protected/apps')).json()
	assert len(response) == 1
	assert any(app['name'] == 'filebrowser' for app in response)

	async def assert_status_down():
		assert all(app['status'] == Status.STOPPED for app in response)

	await retry_async(assert_status_down)

	with open(tmp_path / 'path_root' / 'core' / 'portal_core_db.json') as f:
		db = json.load(f)
	assert 'apps' not in db


@pytest.fixture
def init_db_file_incomplete_migration(tmp_path):
	init_db_file = Path(__file__).parent / 'init_db_incomplete_migration.json'
	dest = tmp_path / 'path_root' / 'core' / 'portal_core_db.json'
	dest.parent.mkdir(parents=True, exist_ok=True)
	dest.touch()
	shutil.copy(init_db_file, dest)


async def test_migration_incomplete_migration(
		init_db_file_incomplete_migration, api_client, tmp_path):
	with open(tmp_path / 'path_root' / 'core' / 'portal_core_db.json') as f:
		db = json.load(f)
	assert 'apps' not in db
	assert 'installed_apps' in db
	assert db['installed_apps']['1']['name'] == 'filebrowser'
