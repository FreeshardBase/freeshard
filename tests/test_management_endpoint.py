from portal_core.service import app_store


def test_install_app(api_client, management_api_mock):
	app_store.refresh_app_store()

	installed_apps = api_client.get('protected/apps').json()
	assert not any(a['name'] == 'app-template-python' for a in installed_apps)

	response = api_client.post(
		'management/apps/app-template-python',
		headers={'authorization': 'constantSharedSecret'}
	)
	response.raise_for_status()

	installed_apps = api_client.get('protected/apps').json()
	assert any(a['name'] == 'app-template-python' for a in installed_apps)
