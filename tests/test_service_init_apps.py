import gconf

import portal_core.service.app_store
import pytest

init_app_conf = {'apps': {'initial_apps': ['filebrowser', 'mock_app']}}

pytest_plugins = ('pytest_asyncio',)


@pytest.mark.asyncio
async def test_add_init_app(api_client, mock_app_store):
	response = api_client.get('/protected/apps')
	response.raise_for_status()
	assert {j['name'] for j in response.json()} == {'filebrowser'}

	with gconf.override_conf(init_app_conf):
		await portal_core.service.app_store.refresh_init_apps()

	response = api_client.get('/protected/apps')
	response.raise_for_status()
	assert {j['name'] for j in response.json()} == {'filebrowser', 'mock_app'}
