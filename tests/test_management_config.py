from fastapi import status

PATH = 'protected/management/resize'


def test_resize_allowed(api_client, management_api_mock):
	response = api_client.put(PATH, json={'size': 'm'})
	response.raise_for_status()
	assert response.status_code == status.HTTP_204_NO_CONTENT


def test_resize_forbidden(api_client, management_api_mock):
	response = api_client.put(PATH, json={'size': 'l'})
	assert response.status_code == status.HTTP_409_CONFLICT
