import pytest

pytestmark = pytest.mark.usefixtures('tempfile_db_config')


def test_add(api_client, pubsub_receiver):
	response = api_client.post('protected/peers', json={
		'id': 'foo',
		'name': 'p1',
		'description': 'my first peer',
		'public_bytes_b64': 'foobarba'
	})
	assert response.status_code == 204
	assert pubsub_receiver.last_topic_equals('peer.add')

	response = api_client.get('protected/peers')
	assert len(response.json()) == 1
