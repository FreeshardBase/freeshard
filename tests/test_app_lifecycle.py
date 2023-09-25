import docker
from fastapi import status

from portal_core.model.app_meta import InstalledApp, Status
from tests.util import retry_async, wait_until_app_installed


async def test_app_starts_and_stops(api_client):
	docker_client = docker.from_env()
	app_name = 'quick_stop'

	response = await api_client.post(f'protected/apps/{app_name}')
	assert response.status_code == status.HTTP_201_CREATED

	await wait_until_app_installed(api_client, app_name)

	assert docker_client.containers.get(app_name).status == 'created'
	assert InstalledApp.parse_obj((await api_client.get(f'protected/apps/{app_name}')).json()).status == Status.STOPPED

	response = await api_client.get('internal/auth', headers={
		'X-Forwarded-Host': f'{app_name}.myportal.org',
		'X-Forwarded-Uri': '/pub'
	})
	response.raise_for_status()

	async def assert_app_running():
		assert docker_client.containers.get(app_name).status == 'running'
		assert InstalledApp.parse_obj(
			(await api_client.get(f'protected/apps/{app_name}')).json()).status == Status.RUNNING

	async def assert_app_exited():
		assert docker_client.containers.get(app_name).status == 'exited'
		assert InstalledApp.parse_obj(
			(await api_client.get(f'protected/apps/{app_name}')).json()).status == Status.STOPPED

	await retry_async(assert_app_running, timeout=10, retry_errors=[AssertionError])
	await retry_async(assert_app_exited, timeout=15, retry_errors=[AssertionError])

	response = await api_client.get('internal/auth', headers={
		'X-Forwarded-Host': f'{app_name}.myportal.org',
		'X-Forwarded-Uri': '/pub'
	})
	response.raise_for_status()

	await retry_async(assert_app_running, timeout=10, retry_errors=[AssertionError])
	assert InstalledApp.parse_obj((await api_client.get(f'protected/apps/{app_name}')).json()).status == Status.RUNNING
	await retry_async(assert_app_exited, timeout=10, retry_errors=[AssertionError])
	assert InstalledApp.parse_obj((await api_client.get(f'protected/apps/{app_name}')).json()).status == Status.STOPPED


async def test_always_on_app_starts(api_client):
	docker_client = docker.from_env()
	app_name = 'always_on'

	response = await api_client.post(f'protected/apps/{app_name}')
	assert response.status_code == status.HTTP_201_CREATED

	await wait_until_app_installed(api_client, app_name)

	async def assert_app_running():
		assert docker_client.containers.get(app_name).status == 'running'

	await retry_async(assert_app_running, timeout=30, retry_errors=[AssertionError])
	assert InstalledApp.parse_obj((await api_client.get(f'protected/apps/{app_name}')).json()).status == Status.RUNNING
