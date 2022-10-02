from common_py import crypto
from common_py.util import retry
from starlette import status

from portal_core.model.peer import Peer


def test_add_and_delete(peer_mock, api_client):
	response = api_client.put('protected/peers', json={
		'id': peer_mock.short_id,
		'name': 'p1',
		'public_bytes_b64': peer_mock.public_key_pem,
	})
	assert response.status_code == status.HTTP_200_OK

	response = api_client.get('protected/peers')
	assert len(response.json()) == 1

	response = api_client.delete(f'protected/peers/{peer_mock.short_id}')
	assert response.status_code == status.HTTP_204_NO_CONTENT

	response = api_client.get('protected/peers')
	assert len(response.json()) == 0


def test_add_only_id(peer_mock, api_client):
	response = api_client.put('protected/peers', json={
		'id': peer_mock.short_id,
	})
	assert response.status_code == status.HTTP_200_OK

	response = api_client.get('protected/peers')
	assert len(response.json()) == 1

	def assert_pubkey_known():
		response = api_client.get(f'protected/peers/{peer_mock.id[:6]}')
		response.raise_for_status()
		whoareyou = Peer(**response.json())
		assert whoareyou.public_bytes_b64 == peer_mock.public_key_pem

	retry(assert_pubkey_known, timeout=10)


def test_add_invalid_id(api_client):
	response = api_client.put('protected/peers', json={
		'id': 'foo',
	})
	assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

	response = api_client.get('protected/peers')
	assert len(response.json()) == 0


def test_add_with_invalid_pubkey(peer_mock, api_client):
	fake_pubkey = crypto.PrivateKey().get_public_key()
	response = api_client.put('protected/peers', json={
		'id': peer_mock.short_id,
		'public_bytes_b64': fake_pubkey.to_bytes().decode(),
	})
	assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


def test_update(peer_mock, api_client):
	response = api_client.put('protected/peers', json={
		'id': peer_mock.short_id,
		'name': 'foo',
	})
	assert response.status_code == status.HTTP_200_OK

	response = api_client.get('protected/peers')
	assert len(response.json()) == 1
	assert response.json()[0]['name'] == 'foo'

	response = api_client.put('protected/peers', json={
		'id': peer_mock.short_id,
		'name': 'bar',
	})
	assert response.status_code == status.HTTP_200_OK

	response = api_client.get('protected/peers')
	assert len(response.json()) == 1
	assert response.json()[0]['name'] == 'bar'
