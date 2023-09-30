from httpx import AsyncClient


async def test_install_app(api_client: AsyncClient, management_api_mock):
	installed_apps = (await api_client.get('protected/apps')).json()
	assert not any(a['name'] == 'mock_app' for a in installed_apps)

	response = await api_client.post(
		'management/apps/mock_app',
		headers={'authorization': 'constantSharedSecret'}
	)
	response.raise_for_status()

	installed_apps = (await api_client.get('protected/apps')).json()
	assert any(a['name'] == 'mock_app' for a in installed_apps)
