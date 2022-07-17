import logging
from time import sleep

import gconf
import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.conninfo import make_conninfo

import portal_core

log = logging.getLogger(__name__)


@pytest.fixture(autouse=True)
def config_override(tmp_path, request):
	print(f'\nUsing temp path: {tmp_path}')
	tempfile_override = {
		'path_root': f'{tmp_path}/path_root',
	}

	# Detects the variable named *config_override* of a test module
	additional_override = getattr(request.module, 'config_override', {})

	with gconf.override_conf(tempfile_override):
		with gconf.override_conf(additional_override):
			yield


@pytest.fixture
def additional_config_override(request):
	"""
	Detects the variable named *config_override* of a test module
	and adds its content as a gconf override.
	"""
	config = getattr(request.module, 'config_override', {})
	with gconf.override_conf(config):
		yield


@pytest.fixture
def init_db(additional_config_override):
	portal_core.database.init_database()


@pytest.fixture
def api_client(init_db) -> TestClient:
	app = portal_core.create_app()

	# Cookies are scoped for the domain, so we have configure the TestClient with it.
	# This way, the TestClient remembers cookies
	whoareyou = TestClient(app).get('public/meta/whoareyou').json()
	yield TestClient(app, base_url=f'https://{whoareyou["domain"]}')


@pytest.fixture(scope='session')
def postgres(request):
	pg_host = gconf.get('services.postgres.host')
	pg_port = gconf.get('services.postgres.port')
	pg_user = gconf.get('services.postgres.user')
	pg_password = gconf.get('services.postgres.password')
	postgres_conn_string = make_conninfo('', host=pg_host, port=pg_port, user=pg_user, password=pg_password)

	print(f'Postgres connection: {postgres_conn_string}')

	if gconf.get('services.postgres.host') == 'localhost':
		request.getfixturevalue('docker_services')

	for i in range(60):
		try:
			sleep(1)
			conn = psycopg.connect(postgres_conn_string)
		except psycopg.OperationalError as e:
			print(e)
		else:
			conn.close()
			break
	else:
		raise TimeoutError('Postgres did not start in time')

	return postgres_conn_string
