from starlette import status

from tests.util import pair_new_terminal


def test_default(api_client, mock_app_store):
	api_client.post('protected/apps/mock_app')

	assert api_client.get('internal/auth', headers={
		'X-Forwarded-Host': 'mock_app.myportal.org',
		'X-Forwarded-Uri': '/pub'
	}).status_code == status.HTTP_200_OK
	assert api_client.get('internal/auth', headers={
		'X-Forwarded-Host': 'mock_app.myportal.org',
		'X-Forwarded-Uri': '/private1'
	}).status_code == status.HTTP_401_UNAUTHORIZED

	pair_new_terminal(api_client)

	assert api_client.get('internal/auth', headers={
		'X-Forwarded-Host': 'mock_app.myportal.org',
		'X-Forwarded-Uri': '/private1'
	}).status_code == status.HTTP_200_OK


def test_headers(api_client, mock_app_store):
	api_client.post('protected/apps/mock_app')

	default_identity = api_client.get('protected/identities/default').json()
	print(default_identity)

	response_public = api_client.get(
		'internal/auth',
		headers={'X-Forwarded-Host': 'mock_app.myportal.org', 'X-Forwarded-Uri': '/public'})
	assert response_public.status_code == status.HTTP_200_OK
	assert response_public.headers['X-Ptl-Client-Type'] == 'anonymous'
	assert response_public.headers['X-Ptl-Client-Id'] == ''
	assert response_public.headers['X-Ptl-Client-Name'] == ''
	assert response_public.headers['X-Ptl-ID'] == default_identity['id']
	assert response_public.headers['X-Ptl-Foo'] == 'baz'

	response_private = api_client.get(
		'internal/auth',
		headers={'X-Forwarded-Host': 'mock_app.myportal.org', 'X-Forwarded-Uri': '/private'})
	assert response_private.status_code == status.HTTP_401_UNAUTHORIZED

	t_name = 'T1'
	pair_new_terminal(api_client, t_name)

	response_public_auth = api_client.get(
		'internal/auth',
		headers={'X-Forwarded-Host': 'mock_app.myportal.org', 'X-Forwarded-Uri': '/public'})
	assert response_public_auth.status_code == status.HTTP_200_OK
	assert response_public_auth.headers['X-Ptl-Client-Type'] == 'terminal'
	assert response_public_auth.headers['X-Ptl-Client-Name'] == t_name
	assert response_public_auth.headers['X-Ptl-ID'] == default_identity['id']
	assert response_public_auth.headers['X-Ptl-Foo'] == 'baz'

	response_auth = api_client.get(
		'internal/auth',
		headers={'X-Forwarded-Host': 'mock_app.myportal.org', 'X-Forwarded-Uri': '/private'})
	assert response_auth.status_code == status.HTTP_200_OK
	assert response_auth.headers['X-Ptl-Client-Type'] == 'terminal'
	assert response_auth.headers['X-Ptl-Client-Name'] == t_name
	assert response_auth.headers['X-Ptl-ID'] == default_identity['id']
	assert response_auth.headers['X-Ptl-Foo'] == 'bar'
