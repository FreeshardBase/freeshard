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
	response = api_client.post('protected/store/branch')
	assert response.status_code == 404
