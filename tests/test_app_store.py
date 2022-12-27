from time import sleep

from portal_core.service.app_store import AppStoreStatus
from portal_core.web.protected.store import StoreBranchIn


def test_set_app_store_branch(api_client):
	data = StoreBranchIn(branch='feature/testing').dict()
	response = api_client.post('protected/store/branch', json=data)
	response.raise_for_status()

	response = api_client.get('protected/store/branch')
	status = AppStoreStatus.parse_obj(response.json())
	assert status.current_branch == 'feature/testing'

	response = api_client.post('protected/store/branch')
	response.raise_for_status()

	response = api_client.get('protected/store/branch')
	status = AppStoreStatus.parse_obj(response.json())
	assert status.current_branch == 'master'


def test_set_unknown_app_store_branch(api_client):
	response = api_client.post('protected/store/branch', json=StoreBranchIn(branch='foo').dict())
	assert response.status_code == 404


def test_get_non_initialized_app_store_branch(api_client):
	response = api_client.get('protected/store/branch')
	response.raise_for_status()


def test_refresh_app_store_autimatically(api_client):
	response = api_client.get('protected/store/branch')
	status0 = AppStoreStatus.parse_obj(response.json())

	api_client.get('protected/store/apps')
	response = api_client.get('protected/store/branch')
	status1 = AppStoreStatus.parse_obj(response.json())

	sleep(1)

	api_client.get('protected/store/apps')
	response = api_client.get('protected/store/branch')
	status2 = AppStoreStatus.parse_obj(response.json())

	sleep(4)

	api_client.get('protected/store/apps')
	response = api_client.get('protected/store/branch')
	status3 = AppStoreStatus.parse_obj(response.json())

	sleep(1)

	api_client.get('protected/store/apps')
	response = api_client.get('protected/store/branch')
	status4 = AppStoreStatus.parse_obj(response.json())

	assert status0.last_update == status1.last_update == status2.last_update
	assert status2.last_update < status3.last_update
	assert status3.last_update == status4.last_update
