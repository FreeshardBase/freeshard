import pytest

from portal_core.service import app_store

pytest_plugins = ('pytest_asyncio',)


# todo: test installation from different branch


@pytest.mark.asyncio
async def test_install_from_store(api_client, mock_app_store):
	installed_apps = api_client.get('protected/apps').json()
	assert not any(a['name'] == 'mock_app' for a in installed_apps)

	await app_store.install_store_app('mock_app')

	installed_apps = api_client.get('protected/apps').json()
	assert any(a['name'] == 'mock_app' for a in installed_apps)


@pytest.mark.asyncio
async def test_install_twice(api_client, mock_app_store):
	await app_store.install_store_app('mock_app')
	with pytest.raises(app_store.AppAlreadyInstalled):
		await app_store.install_store_app('mock_app')
