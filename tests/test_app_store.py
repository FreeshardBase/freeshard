import pytest

import shard_core.service.app_installation
import shard_core.service.app_installation.exceptions
from tests.conftest import requires_test_env
from tests.util import wait_until_all_apps_installed

pytest_plugins = ('pytest_asyncio',)
pytestmark = pytest.mark.asyncio


@requires_test_env('full')
async def test_install_from_store(api_client):
	installed_apps = (await api_client.get('protected/apps')).json()
	assert not any(a['name'] == 'mock_app' for a in installed_apps)

	await shard_core.service.app_installation.install_app_from_store('mock_app')
	await wait_until_all_apps_installed(api_client)

	installed_apps = (await api_client.get('protected/apps')).json()
	assert any(a['name'] == 'mock_app' for a in installed_apps)


@requires_test_env('full')
async def test_install_twice(api_client):
	await shard_core.service.app_installation.install_app_from_store('mock_app')
	await wait_until_all_apps_installed(api_client)
	with pytest.raises(shard_core.service.app_installation.exceptions.AppAlreadyInstalled):
		await shard_core.service.app_installation.install_app_from_store('mock_app')
