from datetime import datetime, timedelta
from time import sleep

import aioresponses
import gconf
import psycopg
import pytest
import responses
import respx
from fastapi.testclient import TestClient
from httpx import Response
from psycopg.conninfo import make_conninfo

import portal_core
from portal_core import Identity
from portal_core.model.identity import OutputIdentity
from portal_core.model.profile import Profile


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

	print(f'\nPostgres connection: {postgres_conn_string}')

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


@pytest.fixture
def management_api_mock():
	management_api = 'https://management-mock'
	config_override = {'management': {'api_url': management_api}}
	mock_profile = Profile(
		vm_id='portal_foobar',
		owner='test owner',
		time_created=datetime.now() - timedelta(days=2),
		time_assigned=datetime.now() - timedelta(days=1),
	)
	with responses.RequestsMock() as rsps, gconf.override_conf(config_override):
		rsps.get(
			f'{management_api}/profile',
			body=mock_profile.json(),
		)
		rsps.add_passthru('')
		yield rsps


@pytest.fixture
def peer_mock():
	peer_identity = Identity.create('peer')
	peer_whoareyou_url = f'https://{peer_identity.domain}/core/public/meta/whoareyou'
	print(f'mocking peer endpoint {peer_whoareyou_url}')

	with respx.mock(assert_all_called=False, base_url=f'https://{peer_identity.domain}/core/') as rx:
		rx.get('/public/meta/whoareyou', name='whoareyou')\
			.mock(Response(status_code=200, json=OutputIdentity(**peer_identity.dict()).dict()))
		yield peer_identity, rx
