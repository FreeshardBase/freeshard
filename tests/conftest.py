import gconf
import pytest
from fastapi.testclient import TestClient

import portal_core


@pytest.fixture(scope='session', autouse=True)
def load_gconf():
	gconf.load('config.yml')


@pytest.fixture
def tempfile_path_config(tmp_path):
	print(f'\nUsing temp path: {tmp_path}')
	override = {
		'database': {'filename': tmp_path / 'app_controller_db.json'},
		'apps': {
			'app_data_dir': tmp_path / 'app_data',
			'app_store': {'sync_dir': tmp_path / 'app_store'},
		},
		'docker_compose': {'compose_filename': tmp_path / 'docker-compose-apps.yml'}
	}
	with gconf.override_conf(override):
		yield


@pytest.fixture
def init_db(tempfile_path_config):
	portal_core.database.init_database()


@pytest.fixture
def api_client(init_db) -> TestClient:
	yield TestClient(portal_core.create_app())
