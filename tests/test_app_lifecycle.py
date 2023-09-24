import docker

from portal_core.model.app_meta import InstalledApp, Status
from tests.util import install_app_and_wait, retry_async


async def test_app_starts_and_stops(api_client):
	docker_client = docker.from_env()

	await install_app_and_wait(api_client, 'quick_stop')

	assert docker_client.containers.get('quick_stop').status == 'created'
	assert InstalledApp.parse_obj((await api_client.get('protected/apps/quick_stop')).json()).status == Status.STOPPED

	response = await api_client.get('internal/auth', headers={
		'X-Forwarded-Host': 'quick_stop.myportal.org',
		'X-Forwarded-Uri': '/pub'
	})
	response.raise_for_status()

	async def assert_app_running():
		assert docker_client.containers.get('quick_stop').status == 'running'
		assert InstalledApp.parse_obj(
			(await api_client.get('protected/apps/quick_stop')).json()).status == Status.RUNNING

	async def assert_app_exited():
		assert docker_client.containers.get('quick_stop').status == 'exited'
		assert InstalledApp.parse_obj(
			(await api_client.get('protected/apps/quick_stop')).json()).status == Status.STOPPED

	await retry_async(assert_app_running, timeout=10, retry_errors=[AssertionError])
	await retry_async(assert_app_exited, timeout=15, retry_errors=[AssertionError])

	response = await api_client.get('internal/auth', headers={
		'X-Forwarded-Host': 'quick_stop.myportal.org',
		'X-Forwarded-Uri': '/pub'
	})
	response.raise_for_status()

	await retry_async(assert_app_running, timeout=10, retry_errors=[AssertionError])
	assert InstalledApp.parse_obj((await api_client.get('protected/apps/quick_stop')).json()).status == Status.RUNNING
	await retry_async(assert_app_exited, timeout=10, retry_errors=[AssertionError])
	assert InstalledApp.parse_obj((await api_client.get('protected/apps/quick_stop')).json()).status == Status.STOPPED


async def test_always_on_app_starts(api_client):
	docker_client = docker.from_env()

	await install_app_and_wait(api_client, 'always_on')

	async def assert_app_running():
		assert docker_client.containers.get('always_on').status == 'running'

	await retry_async(assert_app_running, timeout=30, retry_errors=[AssertionError])
	assert InstalledApp.parse_obj((await api_client.get('protected/apps/always_on')).json()).status == Status.RUNNING
