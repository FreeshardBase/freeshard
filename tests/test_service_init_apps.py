import gconf
from httpx import AsyncClient

import portal_core.service.app_installation
from tests.conftest import requires_test_env
from tests.util import wait_until_all_apps_installed

init_app_conf = {'apps': {'initial_apps': ['filebrowser', 'mock_app']}}


@requires_test_env('full')
async def test_add_init_app(api_client: AsyncClient):
	response = await api_client.get('/protected/apps')
	response.raise_for_status()
	assert {j['name'] for j in response.json()} == {'filebrowser'}

	with gconf.override_conf(init_app_conf):
		await portal_core.service.app_installation.refresh_init_apps()
	await wait_until_all_apps_installed(api_client)

	response = await api_client.get('/protected/apps')
	response.raise_for_status()
	assert {j['name'] for j in response.json()} == {'filebrowser', 'mock_app'}
