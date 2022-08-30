from common_py.util import retry

from portal_core.model.identity import Identity
from portal_core.web.protected.identities import OutputIdentity


def test_add_and_get(api_client):
	i = Identity.create('test id')
	response_post = api_client.put('protected/identities', json=i.dict())
	assert response_post.status_code == 201
	response = api_client.get('protected/identities')
	assert response.status_code == 200
	result = response.json()
	assert len(result) == 2
	result_i = OutputIdentity(**(result[1]))
	assert result_i.name == i.name


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
		'public_name': 'me',
		'description': 'updated identity',
	})
	assert response.status_code == 201

	response = api_client.get('protected/identities')
	assert len(response.json()) == 1
	assert response.json()[0]['public_name'] == 'me'


def test_make_default(api_client):
	response = api_client.put('protected/identities', json={
		'name': 'I2',
		'description': 'a second identity'
	})
	assert response.status_code == 201

	response = api_client.post('protected/identities/I2/make-default')
	assert response.status_code == 204

	response = api_client.get('protected/identities/I2')
	assert response.json()['is_default'] is True
	response = api_client.get('protected/identities/default_identity')
	assert response.json()['is_default'] is False
	response = api_client.get('protected/identities/default')
	assert response.json()['name'] == 'I2'


def test_apply_profile_on_init(management_api_mock, api_client):
	def public_name_verify():
		response = api_client.get('protected/identities/default_identity')
		assert response.json()['public_name'] == 'test'

	retry(public_name_verify, timeout=10)
