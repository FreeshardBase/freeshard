from starlette import status


def test_status_404(api_client):
	response = api_client.get(
		'internal/app_error/404',
		headers={'X-Forwarded-Host': 'foo-app.myportal.org', 'X-Forwarded-Uri': '/pub'})
	assert response.status_code == status.HTTP_404_NOT_FOUND
	assert '404' in response.text


def test_status_500(api_client):
	response = api_client.get(
		'internal/app_error/500',
		headers={'X-Forwarded-Host': 'foo-app.myportal.org', 'X-Forwarded-Uri': '/pub'})
	assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
	assert '500' in response.text
