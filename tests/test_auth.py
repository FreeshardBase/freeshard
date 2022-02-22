import pytest
from starlette import status

from portal_core.database import apps_table
from portal_core.model.app import InstallationReason

pytestmark = pytest.mark.usefixtures('tempfile_path_config')


def test_add(api_client):
	with apps_table() as apps:
		apps.insert({
			'name': 'foo-app',
			'image': 'foo-app:latest',
			'version': '1.2.3',
			'port': 1,
			'authentication': {
				'default_access': 'public',
				'peer_paths': ['/peer1/', '/peer2/'],
				'private_paths': ['/private1/', '/private2/']
			},
			'reason': InstallationReason.CUSTOM,
		})

	response = api_client.get('internal/auth', headers={
		'X-Forwarded-Host': 'foo-app.myportal.org',
		'X-Forwarded-Uri': '/pub'
	})
	assert response.status_code == status.HTTP_200_OK
