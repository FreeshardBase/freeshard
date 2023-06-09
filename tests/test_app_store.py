import pytest

from portal_core.service import app_installation
from tests.util import wait_until_all_apps_installed

pytest_plugins = ('pytest_asyncio',)
pytestmark = pytest.mark.asyncio


# todo: test installation from different branch


async def test_install_from_store(api_client, mock_app_store):
	installed_apps = (await api_client.get('protected/apps')).json()
	assert not any(a['name'] == 'mock_app' for a in installed_apps)

	await app_installation.install_store_app('mock_app')
	await wait_until_all_apps_installed(api_client)

	installed_apps = (await api_client.get('protected/apps')).json()
	assert any(a['name'] == 'mock_app' for a in installed_apps)


async def test_install_twice(api_client, mock_app_store):
	await app_installation.install_store_app('mock_app')
	await wait_until_all_apps_installed(api_client)
	with pytest.raises(app_installation.AppAlreadyInstalled):
		await app_installation.install_store_app('mock_app')
