import pytest
from starlette import status

pytestmark = pytest.mark.usefixtures('tempfile_path_config')


def test_status_404(api_client):
	response = api_client.get(
		'internal/app_error/404',
		headers={'X-Forwarded-Host': 'foo-app.myportal.org', 'X-Forwarded-Uri': '/pub'})
	assert response.status_code == status.HTTP_200_OK
	assert '404' in response.text


def test_status_500(api_client):
	response = api_client.get(
		'internal/app_error/500',
		headers={'X-Forwarded-Host': 'foo-app.myportal.org', 'X-Forwarded-Uri': '/pub'})
	assert response.status_code == status.HTTP_200_OK
	assert '500' in response.text
