from httpx import AsyncClient
from starlette import status

from tests.util import pair_new_terminal, wait_until_app_installed


async def test_default(api_client: AsyncClient):
	app_name = 'mock_app'

	response = await api_client.post(f'protected/apps/{app_name}')
	assert response.status_code == status.HTTP_201_CREATED

	await wait_until_app_installed(api_client, app_name)

	assert (await api_client.get('internal/auth', headers={
		'X-Forwarded-Host': f'{app_name}.myportal.org',
		'X-Forwarded-Uri': '/pub'
	})).status_code == status.HTTP_200_OK
	assert (await api_client.get('internal/auth', headers={
		'X-Forwarded-Host': f'{app_name}.myportal.org',
		'X-Forwarded-Uri': '/private1'
	})).status_code == status.HTTP_401_UNAUTHORIZED

	await pair_new_terminal(api_client)

	assert (await api_client.get('internal/auth', headers={
		'X-Forwarded-Host': f'{app_name}.myportal.org',
		'X-Forwarded-Uri': '/private1'
	})).status_code == status.HTTP_200_OK


async def test_headers(api_client: AsyncClient):
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
