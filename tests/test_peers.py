from starlette import status

from portal_core.model.peer import Peer


def test_add_and_delete(peer_mock_requests, api_client):
	response = api_client.put('protected/peers', json={
		'id': peer_mock_requests.identity.short_id,
	})
	assert response.status_code == status.HTTP_200_OK

	response = api_client.get('protected/peers')
	assert len(response.json()) == 1

	response = api_client.delete(f'protected/peers/{peer_mock_requests.identity.short_id}')
	assert response.status_code == status.HTTP_204_NO_CONTENT

	response = api_client.get('protected/peers')
	assert len(response.json()) == 0


def test_info_is_resolved(peer_mock_requests, api_client):
	response = api_client.put('protected/peers', json={
		'id': peer_mock_requests.identity.short_id,
	})
	assert response.status_code == status.HTTP_200_OK

	response = api_client.get('protected/peers')
	assert len(response.json()) == 1

	response = api_client.get(f'protected/peers/{peer_mock_requests.identity.id[:6]}')
	response.raise_for_status()
	peer = Peer(**response.json())
	assert peer.public_bytes_b64 == peer_mock_requests.identity.public_key_pem
	assert peer.name == 'mock peer'


def test_add_invalid_id(api_client):
	response = api_client.put('protected/peers', json={
		'id': 'foo',
	})
	assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

	response = api_client.get('protected/peers')
	assert len(response.json()) == 0


def test_update_with_real_name(peer_mock_requests, api_client):
	response = api_client.put('protected/peers', json={
		'id': peer_mock_requests.identity.short_id,
		'name': 'foo',
	})
	assert response.status_code == status.HTTP_200_OK

	response = api_client.get('protected/peers')
	assert len(response.json()) == 1
	assert response.json()[0]['name'] == 'mock peer'
