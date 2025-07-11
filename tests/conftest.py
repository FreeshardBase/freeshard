import asyncio
import importlib
import json
import logging
import os
import re
import shutil
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from logging import LogRecord
from pathlib import Path
from typing import List, AsyncGenerator

import gconf
import pytest
import pytest_asyncio
import responses
import yappi
from asgi_lifespan import LifespanManager
from httpx import AsyncClient, ASGITransport
from requests import PreparedRequest
from responses import RequestsMock

from shard_core import app_factory
from shard_core.model.app_meta import VMSize
from shard_core.model.backend.portal_meta import PortalMetaExt, Size
from shard_core.model.identity import OutputIdentity, Identity
from shard_core.model.profile import Profile
from shard_core.service import websocket, app_installation
from shard_core.service.app_tools import get_installed_apps_path
from shard_core.web.internal.call_peer import _get_app_for_ip_address
from tests.util import docker_network_portal, wait_until_all_apps_installed, \
	mock_app_store_path

pytest_plugins = ('pytest_asyncio',)


@pytest.fixture(autouse=True, scope='session')
def setup_all():
	# Logging in with each api_client hit a rate limit or something.
	# We do it one time here, and then patch the login function to noop for each api_client
	asyncio.run(app_installation.login_docker_registries())


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

	with gconf.override_conf(tempfile_override), gconf.override_conf(
			module_override), gconf.override_conf(
		function_override):
		yield


@pytest_asyncio.fixture
async def api_client(mocker) -> AsyncGenerator[AsyncClient]:
	# Modules that define some global state need to be reloaded
	importlib.reload(websocket)
	importlib.reload(app_installation.worker)

	# Mocks must be set up after modules are reloaded or else they will be overwritten
	mock_app_store(mocker)

	async def noop():
		pass

	mocker.patch('shard_core.service.app_installation.login_docker_registries', noop)

	async with docker_network_portal():
		app = app_factory.create_app()
		# for the LifeSpanManager, see: https://github.com/encode/httpx/issues/1024
		async with LifespanManager(app, startup_timeout=20), \
				AsyncClient(transport=ASGITransport(app=app), base_url='https://init', timeout=20) as client:
			whoareyou = (await client.get('/public/meta/whoareyou')).json()
			# Cookies are scoped for the domain,
			# so we have to configure the TestClient with the correct domain.
			# This way, the TestClient remembers cookies
			client.base_url = f'https://{whoareyou["domain"]}'
			await wait_until_all_apps_installed(client)
			yield client


mock_profile = Profile(
	vm_id='shard_foobar',
	owner='test owner',
	owner_email='testowner@foobar.com',
	time_created=datetime.now() - timedelta(days=2),
	time_assigned=datetime.now() - timedelta(days=1),
	vm_size=VMSize.XS,
	max_vm_size=VMSize.M,
)

mock_meta = PortalMetaExt(
	id='shard_foobar',
	owner='test owner',
	owner_email='testowner@foobar.com',
	time_created=datetime.now() - timedelta(days=2),
	time_assigned=datetime.now() - timedelta(days=1),
	size=Size.XS,
	max_size=Size.M,
	from_image='mock_image',
	status='assigned',
)


@contextmanager
def requests_mock_context(*, meta: PortalMetaExt = None, profile: Profile = None):
	management_api = 'https://management-mock'
	controller_base_url = 'https://portal-controller-mock'

	config_override = {
		'management': {'api_url': management_api},
		'portal_controller': {'base_url': controller_base_url}
	}
	management_shared_secret = 'constantSharedSecret'
	with (
		responses.RequestsMock(assert_all_requests_are_fired=False) as rsps,
		gconf.override_conf(config_override)
	):
		rsps.add_callback(
			responses.PUT,
			f'{management_api}/resize',
			callback=requests_mock_resize,
		)
		rsps.post(
			f'{management_api}/app_usage',
		)
		rsps.get(
			f'{management_api}/sharedSecret',
			body=json.dumps({'shared_secret': management_shared_secret}),
		)
		rsps.get(
			f'{controller_base_url}/api/portals/self',
			body=(meta or mock_meta).json(),
		)
		rsps.add_passthru('')
		yield rsps


def requests_mock_resize(request: PreparedRequest):
	data = json.loads(request.body)
	if data['size'] in ['l', 'xl']:
		return 409, {}, ''
	else:
		return 204, {}, ''


@pytest.fixture
def requests_mock():
	with requests_mock_context() as c:
		yield c


@pytest.fixture
def peer_mock_requests(mocker):
	mocker.patch('shard_core.web.internal.call_peer._get_app_for_ip_address',
				 lambda x: 'mock_app')
	_get_app_for_ip_address.cache_clear()
	peer_identity = Identity.create('mock peer')
	print(f'mocking peer {peer_identity.short_id}')
	base_url = f'https://{peer_identity.domain}/core'
	app_url = f'https://mock_app.{peer_identity.domain}'

	with (responses.RequestsMock(assert_all_requests_are_fired=False) as rsps):
		rsps.get(base_url + '/public/meta/whoareyou',
				 json=OutputIdentity(**peer_identity.dict()).dict())
		rsps.get(re.compile(app_url + '/.*'))
		rsps.post(re.compile(app_url + '/.*'))

		rsps.add_passthru('')

		yield PeerMockRequests(
			peer_identity,
			rsps,
		)

	_get_app_for_ip_address.cache_clear()


def mock_app_store(mocker):
	async def mock_download_app_zip(name: str, _=None) -> Path:
		source_zip = mock_app_store_path() / name / f'{name}.zip'
		target_zip = get_installed_apps_path() / name / f'{name}.zip'
		target_zip.parent.mkdir(parents=True, exist_ok=True)
		shutil.copy(source_zip, target_zip.parent)
		print(f'downloaded {name} to {target_zip}')
		return target_zip

	mocker.patch(
		'shard_core.service.app_installation.worker._download_app_zip',
		mock_download_app_zip
	)

	async def mock_app_exists_in_store(name: str) -> bool:
		source_zip = mock_app_store_path() / name / f'{name}.zip'
		return source_zip.exists()

	mocker.patch(
		'shard_core.service.app_installation.util.app_exists_in_store',
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


def requires_test_env(*envs):
	if env := os.environ.get('TEST_ENV'):
		return pytest.mark.skipif(
			env not in list(envs),
			reason=f'Test requires TEST_ENV to be one of {envs}',
		)
	else:
		return pytest.mark.skip(
			reason=f'Test requires TEST_ENV to be one of {envs}',
		)
