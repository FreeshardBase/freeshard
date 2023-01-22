from fastapi import status

from portal_core.web.protected.management import PortalConfig

PATH = 'protected/management/config'


def test_resize_allowed(api_client, management_api_mock):
	config = PortalConfig(size='m')
	response = api_client.put(PATH, json=config.dict())
	response.raise_for_status()
	assert response.status_code == status.HTTP_204_NO_CONTENT


def test_resize_forbidden(api_client, management_api_mock):
	config = PortalConfig(size='l')
	response = api_client.put(PATH, json=config.dict())
	assert response.status_code == status.HTTP_409_CONFLICT
