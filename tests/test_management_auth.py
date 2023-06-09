import pytest
from httpx import AsyncClient

from portal_core import database
from portal_core.service import management
from portal_core.service.management import STORE_KEY_MANAGEMENT_SHARED_KEY


async def test_refresh_shared_secret(api_client: AsyncClient, management_api_mock):
	with pytest.raises(KeyError):
		database.get_value(STORE_KEY_MANAGEMENT_SHARED_KEY)

	management.refresh_shared_secret()

	assert database.get_value(STORE_KEY_MANAGEMENT_SHARED_KEY)


async def test_auth_call_success_with_empty_shared_secret(api_client: AsyncClient, management_api_mock):
	response = await api_client.get(
		'internal/authenticate_management',
		headers={'authorization': 'constantSharedSecret'}
	)
	response.raise_for_status()


async def test_auth_call_success_with_wrong_shared_secret(api_client: AsyncClient, management_api_mock):
	database.set_value(STORE_KEY_MANAGEMENT_SHARED_KEY, 'wrongSecret')
	response = await api_client.get(
		'internal/authenticate_management',
		headers={'authorization': 'constantSharedSecret'}
	)
	response.raise_for_status()


async def test_auth_call_fail_with_empty_shared_secret(api_client: AsyncClient, management_api_mock):
	response = await api_client.get(
		'internal/authenticate_management',
		headers={'authorization': 'failingSecret'}
	)
	assert response.status_code == 401


async def test_auth_call_fail_with_wrong_shared_secret(api_client: AsyncClient, management_api_mock):
	database.set_value(STORE_KEY_MANAGEMENT_SHARED_KEY, 'wrongSecret')
	response = await api_client.get(
		'internal/authenticate_management',
		headers={'authorization': 'failingSecret'}
	)
	assert response.status_code == 401
