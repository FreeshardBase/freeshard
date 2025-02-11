from starlette import status

from tests.conftest import requires_test_env
from tests.util import install_app


@requires_test_env('full')
async def test_status_404(api_client):
	await install_app(api_client, 'mock_app')
	response = await api_client.get(
		'internal/app_error/404',
		headers={'host': 'mock_app.myshard.org', 'X-Forwarded-Uri': '/pub'})
	assert response.status_code == status.HTTP_404_NOT_FOUND
	assert '404' in response.text


@requires_test_env('full')
async def test_status_500(api_client):
	await install_app(api_client, 'mock_app')
	response = await api_client.get(
		'internal/app_error/500',
		headers={'host': 'mock_app.myshard.org', 'X-Forwarded-Uri': '/pub'})
	assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
	assert '500' in response.text
