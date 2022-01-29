import gconf
import psycopg
import pytest
import pytest_docker.plugin
from fastapi.testclient import TestClient
from psycopg.conninfo import make_conninfo

import portal_core


@pytest.fixture(scope='session', autouse=True)
def load_gconf():
	gconf.load('../config.yml', 'config.yml')


@pytest.fixture
def tempfile_path_config(tmp_path):
	print(f'\nUsing temp path: {tmp_path}')
	override = {
		'database': {'filename': tmp_path / 'portal_core_db.json'},
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
	app = portal_core.create_app()

	# Cookies are scoped for the domain, so we have configure the TestClient with it.
	# This way, the TestClient remembers cookies
	whoareyou = TestClient(app).get('public/meta/whoareyou').json()
	domain = whoareyou['domain'][:6].lower()
	yield TestClient(app, base_url=f'https://{domain}.p.getportal.org')


@pytest.fixture(scope='session')
def postgres(docker_services: pytest_docker.plugin.Services):
	postgres_conn_string = make_conninfo('', **gconf.get('services.postgres'))

	def check():
		try:
			conn = psycopg.connect(postgres_conn_string)
		except psycopg.OperationalError as e:
			print(e)
			return False
		else:
			conn.close()
			return True

	docker_services.wait_until_responsive(
		timeout=60.0, pause=1, check=check
	)
	return postgres_conn_string

