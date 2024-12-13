from starlette import status

from portal_core.model.identity import OutputIdentity
from httpx import AsyncClient



async def test_add_and_get(api_client: AsyncClient):
	second_identity = {'name': 'second id', 'email': 'hello@getportal.org'}
	response_post = await api_client.put('protected/identities', json=second_identity)
	assert response_post.status_code == 201
	response = await api_client.get('protected/identities')
	assert response.status_code == 200
	result = response.json()
	assert len(result) == 2
	result_i = OutputIdentity(**(result[1]))
	assert result_i.name == second_identity['name']
	assert result_i.email == second_identity['email']


async def test_get_default(api_client: AsyncClient):
	i_by_list = await api_client.get('protected/identities')
	i_by_list.raise_for_status()
	i_by_default = await api_client.get('protected/identities/default')
	i_by_default.raise_for_status()
	default_identity = i_by_default.json()
	i_by_name = await api_client.get(f'protected/identities/{default_identity["id"]}')
	i_by_name.raise_for_status()
	assert i_by_list.json()[0] == i_by_default.json() == i_by_name.json()


async def test_add_another(api_client: AsyncClient):
	response = await api_client.put('protected/identities', json={
		'name': 'I2',
		'description': 'a second identity'
	})
	assert response.status_code == 201

	response = await api_client.get('protected/identities')
	assert len(response.json()) == 2


async def test_update(api_client: AsyncClient):
	response = await api_client.get('protected/identities/default')
	response.raise_for_status()
	default_identity = response.json()

	response = await api_client.put('protected/identities', json={
		'id': default_identity['id'],
		'email': 'hello@getportal.org',
	})
	assert response.status_code == 201

	response = await api_client.get('protected/identities')
	assert len(response.json()) == 1
	assert response.json()[0]['email'] == 'hello@getportal.org'
	assert response.json()[0]['name'] == 'Portal Owner'


async def test_make_default(api_client: AsyncClient):
	response = await api_client.get('protected/identities/default')
	response.raise_for_status()
	first_identity = response.json()

	second_identity = {'name': 'second id', 'email': 'hello@getportal.org'}
	response = await api_client.put('protected/identities', json=second_identity)
	response.raise_for_status()
	second_identity = response.json()

	response = await api_client.post(f'protected/identities/{second_identity["id"]}/make-default')
	response.raise_for_status()

	response = await api_client.get(f'protected/identities/{second_identity["id"]}')
	assert response.json()['is_default'] is True
	response = await api_client.get(f'protected/identities/{first_identity["id"]}')
	assert response.json()['is_default'] is False
	response = await api_client.get('protected/identities/default')
	assert response.json()['id'] == second_identity['id']


async def test_invalid_email(api_client: AsyncClient):
	response = await api_client.get('protected/identities/default')
	response.raise_for_status()
	default_identity = response.json()

	response = await api_client.put('protected/identities', json={
		'id': default_identity['id'],
		'email': 'i am invalid',
	})
	assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

	response = await api_client.get('protected/identities/default')
	assert response.json()['email'] is None
