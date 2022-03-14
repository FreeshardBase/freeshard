import pytest
from starlette import status

from portal_core.database.database import apps_table
from portal_core.model.app import InstallationReason, AppToInstall
from tests.util import get_pairing_code, add_terminal

pytestmark = pytest.mark.usefixtures('tempfile_path_config')


def test_default_public(api_client):
	with apps_table() as apps:
		apps.insert(AppToInstall(**{
			'name': 'foo-app',
			'image': 'foo-app:latest',
			'version': '1.2.3',
			'port': 1,
			'authentication': {
				'default_access': 'public',
				'private_paths': ['/private1', '/private2']
			},
			'reason': InstallationReason.CUSTOM,
		}).dict())

	assert api_client.get('internal/auth', headers={
		'X-Forwarded-Host': 'foo-app.myportal.org',
		'X-Forwarded-Uri': '/pub'
	}).status_code == status.HTTP_200_OK
	assert api_client.get('internal/auth', headers={
		'X-Forwarded-Host': 'foo-app.myportal.org',
		'X-Forwarded-Uri': '/private1'
	}).status_code == status.HTTP_401_UNAUTHORIZED

	t_name = 'T1'
	pairing_code = get_pairing_code(api_client)
	response = add_terminal(api_client, pairing_code['code'], t_name)
	assert response.status_code == 201

	assert api_client.get('internal/auth', headers={
		'X-Forwarded-Host': 'foo-app.myportal.org',
		'X-Forwarded-Uri': '/private1'
	}).status_code == status.HTTP_200_OK


def test_empty_path_headers(api_client):
	app_name = 'app-with-empty-path-headers'
	with apps_table() as apps:
		apps.insert(AppToInstall(**{
			'description': 'n/a',
			'env_vars': None,
			'image': 'foo-app:latest',
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

	t_name = 'T1'
	pairing_code = get_pairing_code(api_client)
	response = add_terminal(api_client, pairing_code['code'], t_name)
	assert response.status_code == 201

	assert api_client.get('internal/auth', headers={
		'X-Forwarded-Host': f'{app_name}.myportal.org',
		'X-Forwarded-Uri': '/private1'
	}).status_code == status.HTTP_200_OK


def test_no_path_headers(api_client):
	app_name = 'app-with-no-path-headers'
	with apps_table() as apps:
		apps.insert(AppToInstall(**{
			'description': 'n/a',
			'env_vars': None,
			'image': 'foo-app:latest',
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

	t_name = 'T1'
	pairing_code = get_pairing_code(api_client)
	response = add_terminal(api_client, pairing_code['code'], t_name)
	assert response.status_code == 201

	assert api_client.get('internal/auth', headers={
		'X-Forwarded-Host': f'{app_name}.myportal.org',
		'X-Forwarded-Uri': '/private1'
	}).status_code == status.HTTP_200_OK


def test_normal_headers(api_client):
	app_name = 'app-with-normal-headers'
	with apps_table() as apps:
		apps.insert(AppToInstall(**{
			'description': 'n/a',
			'env_vars': None,
			'image': 'foo-app:latest',
			'installation_reason': 'config',
			'name': app_name,
			'paths': {
				'': {
					'access': 'private',
					'headers': {
						'X-Ptl-Client-Id': '{{ client_id }}',
						'X-Ptl-Client-Name': '{{ client_name }}',
						'X-Ptl-Client-Type': 'terminal',
						'X-Ptl-Foo': 'bar'
					}
				},
			},
			'port': 80,
			'services': None,
			'v': '1.0'
		}).dict())

	t_name = 'T1'
	pairing_code = get_pairing_code(api_client)
	response_terminal = add_terminal(api_client, pairing_code['code'], t_name)
	assert response_terminal.status_code == 201

	response_auth = api_client.get(
		'internal/auth',
		headers={'X-Forwarded-Host': f'{app_name}.myportal.org', 'X-Forwarded-Uri': '/private1'})
	assert response_auth.status_code == status.HTTP_200_OK
	assert response_auth.headers['X-Ptl-Client-Type'] == 'terminal'
	assert response_auth.headers['X-Ptl-Client-Name'] == t_name
	assert response_auth.headers['X-Ptl-Foo'] == 'bar'
