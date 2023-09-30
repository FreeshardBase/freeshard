import asyncio
import importlib
import json
import logging
import re
import shutil
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from logging import LogRecord
from pathlib import Path
from typing import List

import gconf
import pytest
import pytest_asyncio
import responses
import yappi
from asgi_lifespan import LifespanManager
from httpx import AsyncClient
from requests import PreparedRequest
from responses import RequestsMock

import portal_core
from portal_core.model.identity import OutputIdentity, Identity
from portal_core.model.profile import Profile
from portal_core.service import websocket
from portal_core.service.app_installation import login_docker_registries
from portal_core.service.app_tools import get_installed_apps_path
from portal_core.web.internal.call_peer import _get_app_for_ip_address
from tests.util import docker_network_portal, wait_until_all_apps_installed, mock_app_store_path

pytest_plugins = ('pytest_asyncio',)


@pytest.fixture(autouse=True, scope='session')
def setup_all():
	# Logging in with each api_client hit a rate limit or something.
	# We do it one time here, and then patch the login function to noop for each api_client
	asyncio.run(login_docker_registries())


@pytest.fixture(autouse=True)
def config_override(tmp_path, request):
	print(f'\nUsing temp path: {tmp_path}')
	tempfile_override = {
		'path_root': f'{tmp_path}/path_root',
	}

	# Detects the variable named *config_override* of a test module
	module_override = getattr(request.module, 'config_override', {})

	# Detects the annotation named @pytest.mark.config_override of a test function
	function_override_mark = request.node.get_closest_marker('config_override')
	function_override = function_override_mark.args[0] if function_override_mark else {}

	with gconf.override_conf(tempfile_override), gconf.override_conf(module_override), gconf.override_conf(
			function_override):
		yield


@pytest_asyncio.fixture
async def api_client(mocker, event_loop, mock_app_store) -> AsyncClient:
	# Modules that define some global state need to be reloaded
	importlib.reload(websocket)

	async def noop():
		pass

	mocker.patch('portal_core.service.app_installation.login_docker_registries', noop)

	async with docker_network_portal():
		app = portal_core.create_app()
		# for the LifeSpanManager, see: https://github.com/encode/httpx/issues/1024
		async with LifespanManager(app), AsyncClient(app=app, base_url='https://init') as client:
			whoareyou = (await client.get('/public/meta/whoareyou')).json()
			# Cookies are scoped for the domain,
			# so we have to configure the TestClient with the correct domain.
			# This way, the TestClient remembers cookies
			client.base_url = f'https://{whoareyou["domain"]}'
			await wait_until_all_apps_installed(client)
			yield client


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
	management_shared_secret = 'constantSharedSecret'
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
		rsps.get(
			f'{management_api}/sharedSecret',
			body=json.dumps({'shared_secret': management_shared_secret}),
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
	mocker.patch('portal_core.web.internal.call_peer._get_app_for_ip_address', lambda x: 'mock_app')
	_get_app_for_ip_address.cache_clear()
	peer_identity = Identity.create('mock peer')
	print(f'mocking peer {peer_identity.short_id}')
	base_url = f'https://{peer_identity.domain}/core'
	app_url = f'https://mock_app.{peer_identity.domain}'

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


@pytest.fixture
def mock_app_store(mocker):

	async def mock_download_app_zip(name: str, _) -> Path:
		source_zip = mock_app_store_path() / name / f'{name}.zip'
		target_zip = get_installed_apps_path() / name / f'{name}.zip'
		target_zip.parent.mkdir(parents=True, exist_ok=True)
		shutil.copy(source_zip, target_zip.parent)
		print(f'downloaded {name} to {target_zip}')
		return target_zip

	mocker.patch(
		'portal_core.service.app_installation._download_app_zip',
		mock_download_app_zip
	)

	async def mock_app_exists_in_store(name: str, _) -> bool:
		source_zip = mock_app_store_path() / name / f'{name}.zip'
		return source_zip.exists()

	mocker.patch(
		'portal_core.service.app_installation._app_exists_in_store',
		mock_app_exists_in_store
	)


@pytest.fixture
def profile_with_yappi():
	yappi.set_clock_type("WALL")
	with yappi.run():
		yield
	yappi.get_func_stats().print_all()


@dataclass
class PeerMockRequests:
	identity: Identity
	mock: RequestsMock


class MemoryLogHandler(logging.Handler):
	def __init__(self):
		super().__init__()
		self.records: List[LogRecord] = []

	def emit(self, record):
		self.records.append(record)


@pytest.fixture
def memory_logger():
	memory_handler = MemoryLogHandler()
	root_logger = logging.getLogger()
	root_logger.addHandler(memory_handler)
	yield memory_handler
	root_logger.removeHandler(memory_handler)
