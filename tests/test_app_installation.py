from fastapi import status
from fastapi.testclient import TestClient

from portal_core.service import app_store


def test_get_initial_apps(api_client: TestClient):
	response = api_client.get('protected/apps').json()
	assert len(response) == 1
	assert response[0]['name'] == 'filebrowser'


def test_install_app(api_client: TestClient):
	new_app = {
		'name': 'new-app',
		'image': 'new-image',
		'port': 80,
		'data_dirs': ['foo', 'bar'],
		'env_vars': {'foo': 'bar'}
	}
	response = api_client.post('protected/apps', json=new_app)
	assert response.status_code == status.HTTP_201_CREATED
	response = api_client.get('protected/apps').json()
	assert len(response) == 2


def test_uninstall_app(api_client: TestClient):
	response = api_client.delete('protected/apps/filebrowser')
	assert response.status_code == status.HTTP_204_NO_CONTENT
	response = api_client.get('protected/apps').json()
	assert len(response) == 0


def test_install_from_store(api_client):
	app_store.refresh_app_store()

	installed_apps = api_client.get('protected/apps').json()
	assert not any(a['name'] == 'app-template-python' for a in installed_apps)

	app_store.install_store_app('app-template-python')

	installed_apps = api_client.get('protected/apps').json()
	assert any(a['name'] == 'app-template-python' for a in installed_apps)
