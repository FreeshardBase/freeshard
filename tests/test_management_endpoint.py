def test_install_app(api_client, management_api_mock, mock_app_store):
	installed_apps = api_client.get('protected/apps').json()
	assert not any(a['name'] == 'mock_app' for a in installed_apps)

	response = api_client.post(
		'management/apps/mock_app',
		headers={'authorization': 'constantSharedSecret'}
	)
	response.raise_for_status()

	installed_apps = api_client.get('protected/apps').json()
	assert any(a['name'] == 'mock_app' for a in installed_apps)
