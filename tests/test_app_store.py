from time import sleep

import pytest

from portal_core.service import app_store
from portal_core.service.app_store import AppStoreStatus
from portal_core.web.protected.store import StoreBranchIn


def test_install_from_store(api_client):
	app_store.refresh_app_store()

	installed_apps = api_client.get('protected/apps').json()
	assert not any(a['name'] == 'app-template-python' for a in installed_apps)

	app_store.install_store_app('app-template-python')

	installed_apps = api_client.get('protected/apps').json()
	assert any(a['name'] == 'app-template-python' for a in installed_apps)


def test_install_twice(api_client):
	app_store.refresh_app_store()
	app_store.install_store_app('app-template-python')
	with pytest.raises(app_store.AppAlreadyInstalled):
		app_store.install_store_app('app-template-python')


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


def test_refresh_app_store_automatically(api_client):
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

	sleep(1)

	api_client.get('protected/store/apps', params={'refresh': True})
	response = api_client.get('protected/store/branch')
	status5 = AppStoreStatus.parse_obj(response.json())

	assert status0.last_update == status1.last_update == status2.last_update
	assert status2.last_update < status3.last_update
	assert status3.last_update == status4.last_update
	assert status4.last_update < status5.last_update
