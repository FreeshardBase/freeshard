from portal_core.model.identity import Identity
from portal_core.web.protected.identities import OutputIdentity


test_identity = i = Identity.create('test id', email='hello@getportal.org')


def test_add_and_get(api_client):
	response_post = api_client.put('protected/identities', json=test_identity.dict())
	assert response_post.status_code == 201
	response = api_client.get('protected/identities')
	assert response.status_code == 200
	result = response.json()
	assert len(result) == 2
	result_i = OutputIdentity(**(result[1]))
	assert result_i.name == test_identity.name
	assert result_i.email == test_identity.email


def test_get_default(api_client):
	i_by_list = api_client.get('protected/identities')
	i_by_list.raise_for_status()
	i_by_default = api_client.get('protected/identities/default')
	i_by_default.raise_for_status()
	i_by_name = api_client.get('protected/identities/default_identity')
	i_by_name.raise_for_status()
	assert i_by_list.json()[0] == i_by_default.json() == i_by_name.json()


def test_add_another(api_client):
	response = api_client.put('protected/identities', json={
		'name': 'I2',
		'description': 'a second identity'
	})
	assert response.status_code == 201

	response = api_client.get('protected/identities')
	assert len(response.json()) == 2


def test_update(api_client):
	response = api_client.put('protected/identities', json={
		'name': 'default_identity',
		'email': 'hello@getportal.org',
		'description': 'updated identity',
	})
	assert response.status_code == 201

	response = api_client.get('protected/identities')
	assert len(response.json()) == 1
	assert response.json()[0]['email'] == 'hello@getportal.org'


def test_make_default(api_client):
	response = api_client.put('protected/identities', json=test_identity.dict())
	response.raise_for_status()

	response = api_client.post(f'protected/identities/{test_identity.name}/make-default')
	response.raise_for_status()

	response = api_client.get(f'protected/identities/{test_identity.name}')
	assert response.json()['is_default'] is True
	response = api_client.get('protected/identities/default_identity')
	assert response.json()['is_default'] is False
	response = api_client.get('protected/identities/default')
	assert response.json()['name'] == test_identity.name
