from starlette import status
from httpx import AsyncClient

from tests.util import pair_new_terminal, install_app_and_wait


async def test_default(api_client: AsyncClient, mock_app_store):
	await install_app_and_wait(api_client, 'mock_app')

	assert (await api_client.get('internal/auth', headers={
		'X-Forwarded-Host': 'mock_app.myportal.org',
		'X-Forwarded-Uri': '/pub'
	})).status_code == status.HTTP_200_OK
	assert (await api_client.get('internal/auth', headers={
		'X-Forwarded-Host': 'mock_app.myportal.org',
		'X-Forwarded-Uri': '/private1'
	})).status_code == status.HTTP_401_UNAUTHORIZED

	await pair_new_terminal(api_client)

	assert (await api_client.get('internal/auth', headers={
		'X-Forwarded-Host': 'mock_app.myportal.org',
		'X-Forwarded-Uri': '/private1'
	})).status_code == status.HTTP_200_OK


async def test_headers(api_client: AsyncClient, mock_app_store):
	await api_client.post('protected/apps/mock_app')

	default_identity = (await api_client.get('protected/identities/default')).json()
	print(default_identity)

	response_public = await api_client.get(
		'internal/auth',
		headers={'X-Forwarded-Host': 'mock_app.myportal.org', 'X-Forwarded-Uri': '/public'})
	assert response_public.status_code == status.HTTP_200_OK
	assert response_public.headers['X-Ptl-Client-Type'] == 'anonymous'
	assert response_public.headers['X-Ptl-Client-Id'] == ''
	assert response_public.headers['X-Ptl-Client-Name'] == ''
	assert response_public.headers['X-Ptl-ID'] == default_identity['id']
	assert response_public.headers['X-Ptl-Foo'] == 'baz'

	response_private = await api_client.get(
		'internal/auth',
		headers={'X-Forwarded-Host': 'mock_app.myportal.org', 'X-Forwarded-Uri': '/private'})
	assert response_private.status_code == status.HTTP_401_UNAUTHORIZED

	t_name = 'T1'
	await pair_new_terminal(api_client, t_name)

	response_public_auth = await api_client.get(
		'internal/auth',
		headers={'X-Forwarded-Host': 'mock_app.myportal.org', 'X-Forwarded-Uri': '/public'})
	assert response_public_auth.status_code == status.HTTP_200_OK
	assert response_public_auth.headers['X-Ptl-Client-Type'] == 'terminal'
	assert response_public_auth.headers['X-Ptl-Client-Name'] == t_name
	assert response_public_auth.headers['X-Ptl-ID'] == default_identity['id']
	assert response_public_auth.headers['X-Ptl-Foo'] == 'baz'

	response_auth = await api_client.get(
		'internal/auth',
		headers={'X-Forwarded-Host': 'mock_app.myportal.org', 'X-Forwarded-Uri': '/private'})
	assert response_auth.status_code == status.HTTP_200_OK
	assert response_auth.headers['X-Ptl-Client-Type'] == 'terminal'
	assert response_auth.headers['X-Ptl-Client-Name'] == t_name
	assert response_auth.headers['X-Ptl-ID'] == default_identity['id']
	assert response_auth.headers['X-Ptl-Foo'] == 'bar'


async def test_fail_unknown_app(api_client: AsyncClient):
	assert (await api_client.get('internal/auth', headers={
		'X-Forwarded-Host': 'unknown.myportal.org',
		'X-Forwarded-Uri': '/pub'
	})).status_code == status.HTTP_404_NOT_FOUND
