import json
import os
import re
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from time import sleep

import gconf
import psycopg
import pytest
import responses
from fastapi.testclient import TestClient
from psycopg.conninfo import make_conninfo
from requests import PreparedRequest
from responses import RequestsMock

import portal_core
from portal_core import Identity
from portal_core.model.identity import OutputIdentity
from portal_core.model.profile import Profile
from portal_core.web.internal.call_peer import _get_app_for_ip_address


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
def init_db(config_override):
	portal_core.database.init_database()


@pytest.fixture
def api_client(init_db) -> TestClient:
	os.environ['CONFIG'] = str(Path(__file__).parent / 'config.yml')

	app = portal_core.create_app()

	# Cookies are scoped for the domain, so we have to configure the TestClient with it.
	# This way, the TestClient remembers cookies
	whoareyou = TestClient(app).get('public/meta/whoareyou').json()
	with TestClient(app, base_url=f'https://{whoareyou["domain"]}') as client:
		yield client


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


mock_profile = Profile(
	vm_id='portal_foobar',
	owner='test owner',
	owner_email='testowner@foobar.com',
	time_created=datetime.now() - timedelta(days=2),
	time_assigned=datetime.now() - timedelta(days=1),
	portal_size='xs',
	max_portal_size='m',
)


@contextmanager
def management_api_mock_context(profile: Profile = None):
	management_api = 'https://management-mock'
	config_override = {'management': {'api_url': management_api}}
	with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps, gconf.override_conf(config_override):
		rsps.get(
			f'{management_api}/profile',
			body=(profile or mock_profile).json(),
		)
		rsps.add_callback(
			responses.PUT,
			f'{management_api}/resize',
			callback=management_api_mock_resize,
		)
		rsps.post(
			f'{management_api}/app_usage',
		)
		rsps.add_passthru('')
		yield rsps


def management_api_mock_resize(request: PreparedRequest):
	data = json.loads(request.body)
	if data['size'] in ['l', 'xl']:
		return 409, {}, ''
	else:
		return 204, {}, ''


@pytest.fixture
def management_api_mock():
	with management_api_mock_context() as c:
		yield c


@pytest.fixture
def peer_mock_requests(mocker):
	mocker.patch('portal_core.web.internal.call_peer._get_app_for_ip_address', lambda x: 'myapp')
	_get_app_for_ip_address.cache_clear()
	peer_identity = Identity.create('mock peer')
	print(f'mocking peer {peer_identity.short_id}')
	base_url = f'https://{peer_identity.domain}/core'
	app_url = f'https://myapp.{peer_identity.domain}'

	with (responses.RequestsMock(assert_all_requests_are_fired=False) as rsps):
		rsps.get(base_url + '/public/meta/whoareyou', json=OutputIdentity(**peer_identity.dict()).dict())
		rsps.get(re.compile(app_url + '/.*'))
		rsps.post(re.compile(app_url + '/.*'))

		rsps.add_passthru('')

		yield PeerMockRequests(
			peer_identity,
			rsps,
		)

	_get_app_for_ip_address.cache_clear()


@dataclass
class PeerMockRequests:
	identity: Identity
	mock: RequestsMock
