from httpx import AsyncClient
from starlette import status

from shard_core.model.peer import Peer
from tests.conftest import requires_test_env


@requires_test_env('full')
async def test_add_and_delete(peer_mock_requests, api_client: AsyncClient):
	response = await api_client.put('protected/peers', json={
		'id': peer_mock_requests.identity.short_id,
	})
	assert response.status_code == status.HTTP_200_OK

	response = await api_client.get('protected/peers')
	assert len(response.json()) == 1

	response = await api_client.delete(f'protected/peers/{peer_mock_requests.identity.short_id}')
	assert response.status_code == status.HTTP_204_NO_CONTENT

	response = await api_client.get('protected/peers')
	assert len(response.json()) == 0


@requires_test_env('full')
async def test_info_is_resolved(api_client: AsyncClient, peer_mock_requests):
	response = await api_client.put('protected/peers', json={
		'id': peer_mock_requests.identity.short_id,
	})
	assert response.status_code == status.HTTP_200_OK

	response = await api_client.get('protected/peers')
	assert len(response.json()) == 1

	response = await api_client.get(f'protected/peers/{peer_mock_requests.identity.id[:6]}')
	response.raise_for_status()
	peer = Peer(**response.json())
	assert peer.public_bytes_b64 == peer_mock_requests.identity.public_key_pem
	assert peer.name == 'mock peer'


@requires_test_env('full')
async def test_add_invalid_id(api_client: AsyncClient):
	response = await api_client.put('protected/peers', json={
		'id': 'foo',
	})
	assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

	response = await api_client.get('protected/peers')
	assert len(response.json()) == 0


@requires_test_env('full')
async def test_update_with_real_name(api_client: AsyncClient, peer_mock_requests):
	response = await api_client.put('protected/peers', json={
		'id': peer_mock_requests.identity.short_id,
		'name': 'foo',
	})
	assert response.status_code == status.HTTP_200_OK

	response = await api_client.get('protected/peers')
	assert len(response.json()) == 1
	assert response.json()[0]['name'] == 'mock peer'


@requires_test_env('full')
async def test_is_unreachable(api_client: AsyncClient):
	response = await api_client.put('protected/peers', json={
		'id': 'foobar',
	})
	assert response.status_code == status.HTTP_200_OK

	response = await api_client.get('protected/peers')
	assert len(response.json()) == 1
	assert response.json()[0]['is_reachable'] is False
