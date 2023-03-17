from starlette import status

from portal_core.database.database import apps_table
from portal_core.model.app import InstallationReason, AppToInstall
from portal_core.service import app_infra
from tests.util import create_apps_from_docker_compose, WAITING_DOCKER_IMAGE, \
	pair_new_terminal, install_test_app


def test_default_public(api_client):
	with apps_table() as apps:  # type: Table
		apps.truncate()
		apps.insert(AppToInstall(**{
			'name': 'foo-app',
			'image': WAITING_DOCKER_IMAGE,
			'port': 1,
			'authentication': {
				'default_access': 'public',
				'private_paths': ['/private1', '/private2']
			},
			'reason': InstallationReason.CUSTOM,
		}).dict())

	app_infra.refresh_app_infra()
	with create_apps_from_docker_compose():
		assert api_client.get('internal/auth', headers={
			'X-Forwarded-Host': 'foo-app.myportal.org',
			'X-Forwarded-Uri': '/pub'
		}).status_code == status.HTTP_200_OK
		assert api_client.get('internal/auth', headers={
			'X-Forwarded-Host': 'foo-app.myportal.org',
			'X-Forwarded-Uri': '/private1'
		}).status_code == status.HTTP_401_UNAUTHORIZED

		pair_new_terminal(api_client)

		assert api_client.get('internal/auth', headers={
			'X-Forwarded-Host': 'foo-app.myportal.org',
			'X-Forwarded-Uri': '/private1'
		}).status_code == status.HTTP_200_OK


def test_empty_path_headers(api_client):
	app_name = 'app-with-empty-path-headers'
	with apps_table() as apps:  # type: Table
		apps.truncate()
		apps.insert(AppToInstall(**{
			'description': 'n/a',
			'env_vars': None,
			'image': WAITING_DOCKER_IMAGE,
			'installation_reason': 'config',
			'name': app_name,
			'paths': {
				'': {
					'access': 'private',
					'headers': None
				},
			},
			'port': 80,
			'services': None,
			'v': '1.0'
		}).dict())

	app_infra.refresh_app_infra()
	with create_apps_from_docker_compose():
		pair_new_terminal(api_client)
		assert api_client.get('internal/auth', headers={
			'X-Forwarded-Host': f'{app_name}.myportal.org',
			'X-Forwarded-Uri': '/private1'
		}).status_code == status.HTTP_200_OK


def test_no_path_headers(api_client):
	app_name = 'app-with-no-path-headers'
	with apps_table() as apps:  # type: Table
		apps.truncate()
		apps.insert(AppToInstall(**{
			'description': 'n/a',
			'env_vars': None,
			'image': WAITING_DOCKER_IMAGE,
			'installation_reason': 'config',
			'name': app_name,
			'paths': {
				'': {
					'access': 'private',
				},
			},
			'port': 80,
			'services': None,
			'v': '1.0'
		}).dict())

	app_infra.refresh_app_infra()
	with create_apps_from_docker_compose():
		pair_new_terminal(api_client)
		assert api_client.get('internal/auth', headers={
			'X-Forwarded-Host': f'{app_name}.myportal.org',
			'X-Forwarded-Uri': '/private1'
		}).status_code == status.HTTP_200_OK


def test_normal_headers(api_client):
	with install_test_app():
		default_identity = api_client.get('protected/identities/default').json()
		print(default_identity)

		response_public = api_client.get(
			'internal/auth',
			headers={'X-Forwarded-Host': 'myapp.myportal.org', 'X-Forwarded-Uri': '/public'})
		assert response_public.status_code == status.HTTP_200_OK
		assert response_public.headers['X-Ptl-Client-Type'] == 'anonymous'
		assert response_public.headers['X-Ptl-Client-Id'] == ''
		assert response_public.headers['X-Ptl-Client-Name'] == ''
		assert response_public.headers['X-Ptl-ID'] == default_identity['id']
		assert response_public.headers['X-Ptl-Foo'] == 'baz'

		response_private = api_client.get(
			'internal/auth',
			headers={'X-Forwarded-Host': 'myapp.myportal.org', 'X-Forwarded-Uri': '/private'})
		assert response_private.status_code == status.HTTP_401_UNAUTHORIZED

		t_name = 'T1'
		pair_new_terminal(api_client, t_name)

		response_public_auth = api_client.get(
			'internal/auth',
			headers={'X-Forwarded-Host': 'myapp.myportal.org', 'X-Forwarded-Uri': '/public'})
		assert response_public_auth.status_code == status.HTTP_200_OK
		assert response_public_auth.headers['X-Ptl-Client-Type'] == 'terminal'
		assert response_public_auth.headers['X-Ptl-Client-Name'] == t_name
		assert response_public_auth.headers['X-Ptl-ID'] == default_identity['id']
		assert response_public_auth.headers['X-Ptl-Foo'] == 'baz'

		response_auth = api_client.get(
			'internal/auth',
			headers={'X-Forwarded-Host': 'myapp.myportal.org', 'X-Forwarded-Uri': '/private'})
		assert response_auth.status_code == status.HTTP_200_OK
		assert response_auth.headers['X-Ptl-Client-Type'] == 'terminal'
		assert response_auth.headers['X-Ptl-Client-Name'] == t_name
		assert response_auth.headers['X-Ptl-ID'] == default_identity['id']
		assert response_auth.headers['X-Ptl-Foo'] == 'bar'
