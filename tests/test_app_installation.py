import pytest
from fastapi import status
from fastapi.testclient import TestClient
import docker
from docker.errors import NotFound


def test_get_initial_apps(api_client: TestClient):
	response = api_client.get('protected/apps').json()
	assert len(response) == 1
	assert response[0]['name'] == 'filebrowser'


def test_install_app(api_client: TestClient, mock_app_store):
	docker_client = docker.from_env()

	response = api_client.post('protected/apps/mock_app')
	assert response.status_code == status.HTTP_201_CREATED

	docker_client.containers.get('mock_app')

	response = api_client.get('protected/apps').json()
	assert len(response) == 2


def test_install_app_twice(api_client: TestClient, mock_app_store):
	response = api_client.post('protected/apps/mock_app')
	assert response.status_code == status.HTTP_201_CREATED

	response = api_client.post('protected/apps/mock_app')
	assert response.status_code == status.HTTP_409_CONFLICT


def test_uninstall_app(api_client: TestClient):
	docker_client = docker.from_env()
	docker_client.containers.get('filebrowser')

	response = api_client.delete('protected/apps/filebrowser')
	assert response.status_code == status.HTTP_204_NO_CONTENT

	response = api_client.get('protected/apps').json()
	assert len(response) == 0

	with pytest.raises(NotFound):
		docker_client.containers.get('filebrowser')
