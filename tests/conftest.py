import logging
from time import sleep

import gconf
import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.conninfo import make_conninfo

import portal_core

log = logging.getLogger(__name__)


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
def postgres(request):
	postgres_conn_string = make_conninfo('', **gconf.get('services.postgres'))
	print(f'Postgres connection: {postgres_conn_string}')

	if gconf.get('services.postgres.host') == 'localhost':
		request.getfixturevalue('docker_services')

	for i in range(60):
		try:
			sleep(1)
			conn = psycopg.connect(postgres_conn_string)
		except psycopg.OperationalError as e:
			pass
		else:
			conn.close()
			break
	else:
		raise TimeoutError('Postgres did not start in time')

	return postgres_conn_string
