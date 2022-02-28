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


