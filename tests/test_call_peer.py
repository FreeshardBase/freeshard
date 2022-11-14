from common_py.crypto import PublicKey
from fastapi import status
from http_message_signatures import algorithms
from requests import PreparedRequest, Request
from requests_http_signature import HTTPSignatureAuth

from portal_core.model.identity import OutputIdentity
from tests.util import verify_signature_auth, install_test_app, modify_request_like_traefik_forward_auth


def test_call_peer_from_app_basic(peer_mock_requests, api_client):
	portal_identity = OutputIdentity(**api_client.get('public/meta/whoareyou').json())
	pubkey = PublicKey(portal_identity.public_key_pem)

	path = '/foo/bar'
	response = api_client.get(f'internal/call_peer/{peer_mock_requests.identity.short_id}{path}')
	assert response.status_code == 200

	received_request = peer_mock_requests.mock.calls[0].request
	v = verify_signature_auth(received_request, pubkey)
	assert portal_identity.id.startswith(v.parameters['keyid'])
	assert received_request.path_url == path


def test_call_peer_from_app_post(peer_mock_requests, api_client):
	portal_identity = OutputIdentity(**api_client.get('public/meta/whoareyou').json())
	pubkey = PublicKey(portal_identity.public_key_pem)

	path = '/foo/bar'
	response = api_client.post(
		f'internal/call_peer/{peer_mock_requests.identity.short_id}{path}',
		data=b'foo data bar')
	assert response.status_code == 200

	received_request: PreparedRequest = peer_mock_requests.mock.calls[0].request
	v = verify_signature_auth(received_request, pubkey)
	assert portal_identity.id.startswith(v.parameters['keyid'])
	assert received_request.path_url == path
	assert received_request.body == b'foo data bar'


def test_peer_auth_basic(peer_mock_requests, api_client):
	peer = peer_mock_requests.identity
	peer_auth = HTTPSignatureAuth(
		signature_algorithm=algorithms.RSA_PSS_SHA512,
		key_id=peer.short_id,
		key=peer.private_key.encode(),
	)
	whoareyou = OutputIdentity(**api_client.get('public/meta/whoareyou').json())

	request_to_traefik = Request(
		method='GET',
		url=f'https://myapp.{whoareyou.domain}/peer',
		auth=peer_auth,
	).prepare()

	request_to_auth = modify_request_like_traefik_forward_auth(request_to_traefik)

	with install_test_app():

		response = api_client.send(request_to_auth)
		assert response.status_code == status.HTTP_401_UNAUTHORIZED

		api_client.put('protected/peers', json={
			'id': peer.short_id,
			'name': 'peer',
		})

		response = api_client.send(request_to_auth)
		response.raise_for_status()
		assert response.headers['X-Ptl-Client-Type'] == 'peer'
		assert response.headers['X-Ptl-Client-Id'] == peer.id
		assert response.headers['X-Ptl-Client-Name'] == peer.name
