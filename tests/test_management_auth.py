import pytest

from portal_core import database
from portal_core.service import management
from portal_core.service.management import STORE_KEY_MANAGEMENT_SHARED_KEY


def test_refresh_shared_secret(api_client, management_api_mock):
	with pytest.raises(KeyError):
		database.get_value(STORE_KEY_MANAGEMENT_SHARED_KEY)

	management.refresh_shared_secret()

	assert database.get_value(STORE_KEY_MANAGEMENT_SHARED_KEY)


def test_auth_call_success_with_empty_shared_secret(api_client, management_api_mock):
	response = api_client.get(
		'internal/authenticate_management',
		headers={'authorization': 'constantSharedSecret'}
	)
	response.raise_for_status()


def test_auth_call_success_with_wrong_shared_secret(api_client, management_api_mock):
	database.set_value(STORE_KEY_MANAGEMENT_SHARED_KEY, 'wrongSecret')
	response = api_client.get(
		'internal/authenticate_management',
		headers={'authorization': 'constantSharedSecret'}
	)
	response.raise_for_status()


def test_auth_call_fail_with_empty_shared_secret(api_client, management_api_mock):
	response = api_client.get(
		'internal/authenticate_management',
		headers={'authorization': 'failingSecret'}
	)
	assert response.status_code == 401


def test_auth_call_fail_with_wrong_shared_secret(api_client, management_api_mock):
	database.set_value(STORE_KEY_MANAGEMENT_SHARED_KEY, 'wrongSecret')
	response = api_client.get(
		'internal/authenticate_management',
		headers={'authorization': 'failingSecret'}
	)
	assert response.status_code == 401
