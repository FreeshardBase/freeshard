import pytest

from portal_core.model.identity import Identity
from portal_core.web.protected.identities import OutputIdentity

pytestmark = pytest.mark.usefixtures('tempfile_path_config')


def test_add_and_get(api_client):
	i = Identity.create('test id')
	response_post = api_client.post('protected/identities', json=i.dict())
	assert response_post.status_code == 201
	response = api_client.get('protected/identities')
	assert response.status_code == 200
	result = response.json()
	assert len(result) == 2
	result_i = OutputIdentity(**(result[1]))
	assert result_i.name == i.name


def test_get_default(api_client):
	i_by_list = api_client.get('protected/identities').json()[0]
	i_by_default = api_client.get('protected/identities/default').json()
	i_by_name = api_client.get('protected/identities/default_identity').json()

	assert i_by_list['id'] == i_by_default['id'] == i_by_name['id']
	assert i_by_list['name'] == i_by_default['name'] == i_by_name['name']
	assert i_by_list['description'] == i_by_default['description'] == i_by_name['description']
	assert i_by_list['public_key_pem'] == i_by_default['public_key_pem'] == i_by_name['public_key_pem']


def test_add_another(api_client, pubsub_receiver):
	response = api_client.post('protected/identities', json={
		'name': 'I2',
		'description': 'a second identity'
	})
	assert response.status_code == 201

	response = api_client.get('protected/identities')
	assert len(response.json()) == 2
	assert any(pubsub_receiver == ('identity.add', i) for i in response.json())
	assert any(i_json == pubsub_receiver.last_message_json for i_json in response.json())


def test_add_conflict(api_client):
	response = api_client.post('protected/identities', json={
		'name': 'default_identity',
		'description': 'a second identity'
	})
	assert response.status_code == 409

	response = api_client.get('protected/identities')
	assert len(response.json()) == 1


def test_make_default(api_client, pubsub_receiver):
	response = api_client.post('protected/identities', json={
		'name': 'I2',
		'description': 'a second identity'
	})
	assert response.status_code == 201

	response = api_client.post('protected/identities/I2/make-default')
	assert response.status_code == 204

	response = api_client.get('protected/identities/I2')
	assert response.json()['is_default'] is True
	assert pubsub_receiver == ('identity.modify', response.json())
	response = api_client.get('protected/identities/default_identity')
	assert response.json()['is_default'] is False
	response = api_client.get('protected/identities/default')
	assert response.json()['name'] == 'I2'
