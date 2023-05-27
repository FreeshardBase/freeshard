import docker
from common_py.util import retry

from portal_core.model.app_meta import InstalledApp, Status


def test_app_starts_and_stops(api_client, mock_app_store):
	docker_client = docker.from_env()

	response = api_client.post('protected/apps/quick_stop')
	response.raise_for_status()

	assert docker_client.containers.get('quick_stop').status == 'created'
	assert InstalledApp.parse_obj(api_client.get('protected/apps/quick_stop').json()).status == Status.STOPPED

	response = api_client.get('internal/auth', headers={
		'X-Forwarded-Host': 'quick_stop.myportal.org',
		'X-Forwarded-Uri': '/pub'
	})
	response.raise_for_status()

	def assert_app_running():
		assert docker_client.containers.get('quick_stop').status == 'running'

	def assert_app_exited():
		assert docker_client.containers.get('quick_stop').status == 'exited'

	retry(assert_app_running, timeout=10, retry_errors=[AssertionError])
	assert InstalledApp.parse_obj(api_client.get('protected/apps/quick_stop').json()).status == Status.RUNNING
	retry(assert_app_exited, timeout=15, retry_errors=[AssertionError])
	assert InstalledApp.parse_obj(api_client.get('protected/apps/quick_stop').json()).status == Status.STOPPED

	response = api_client.get('internal/auth', headers={
		'X-Forwarded-Host': 'quick_stop.myportal.org',
		'X-Forwarded-Uri': '/pub'
	})
	response.raise_for_status()

	retry(assert_app_running, timeout=10, retry_errors=[AssertionError])
	assert InstalledApp.parse_obj(api_client.get('protected/apps/quick_stop').json()).status == Status.RUNNING
	retry(assert_app_exited, timeout=10, retry_errors=[AssertionError])
	assert InstalledApp.parse_obj(api_client.get('protected/apps/quick_stop').json()).status == Status.STOPPED


def test_always_on_app_starts(api_client, mock_app_store):
	docker_client = docker.from_env()

	response = api_client.post('protected/apps/always_on')
	response.raise_for_status()

	def assert_app_running():
		assert docker_client.containers.get('always_on').status == 'running'

	retry(assert_app_running, timeout=30, retry_errors=[AssertionError])
	assert InstalledApp.parse_obj(api_client.get('protected/apps/always_on').json()).status == Status.RUNNING
