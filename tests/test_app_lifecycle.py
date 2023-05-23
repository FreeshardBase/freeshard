import docker
from common_py.util import retry

from portal_core.database.database import apps_table
from portal_core.model.app_meta import AppToInstall, InstallationReason
from portal_core.service import app_infra
from tests.util import create_apps_from_docker_compose, WAITING_DOCKER_IMAGE


def test_app_starts_and_stops(api_client):
	docker_client = docker.from_env()
	app = AppToInstall(**{
		'v': '3.1',
		'name': 'foo-app',
		'image': WAITING_DOCKER_IMAGE,
		'version': '1.2.3',
		'port': 1,
		'paths': {
			'': {'access': 'public'},
		},
		'lifecycle': {'idle_time_for_shutdown': 5},
		'reason': InstallationReason.CUSTOM,
	})
	with apps_table() as apps:  # type: Table
		apps.truncate()
		apps.insert(app.dict())

	app_infra.write_traefik_dyn_config()
	with create_apps_from_docker_compose():
		assert docker_client.containers.get('foo-app').status == 'created'
		api_client.get('internal/auth', headers={
			'X-Forwarded-Host': 'foo-app.myportal.org',
			'X-Forwarded-Uri': '/pub'
		})

		def assert_app_running():
			assert docker_client.containers.get('foo-app').status == 'running'

		def assert_app_exited():
			assert docker_client.containers.get('foo-app').status == 'exited'

		retry(assert_app_running, timeout=10, retry_errors=[AssertionError])
		retry(assert_app_exited, timeout=15, retry_errors=[AssertionError])

		api_client.get('internal/auth', headers={
			'X-Forwarded-Host': 'foo-app.myportal.org',
			'X-Forwarded-Uri': '/pub'
		})

		retry(assert_app_running, timeout=10, retry_errors=[AssertionError])
		retry(assert_app_exited, timeout=10, retry_errors=[AssertionError])


def test_always_on_app_starts(api_client):
	docker_client = docker.from_env()
	app = AppToInstall(**{
		'v': '3.1',
		'name': 'foo-app',
		'image': WAITING_DOCKER_IMAGE,
		'version': '1.2.3',
		'port': 1,
		'paths': {
			'': {'access': 'public'},
		},
		'lifecycle': {'always_on': True},
		'reason': InstallationReason.CUSTOM,
	})
	with apps_table() as apps:  # type: Table
		apps.truncate()
		apps.insert(app.dict())

	app_infra.write_traefik_dyn_config()
	with create_apps_from_docker_compose():
		def assert_app_running():
			assert docker_client.containers.get('foo-app').status == 'running'

		retry(assert_app_running, timeout=10, retry_errors=[AssertionError])
