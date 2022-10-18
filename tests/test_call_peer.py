from common_py.crypto import PublicKey
from fastapi import status
from http_message_signatures import algorithms
from requests_http_signature import HTTPSignatureAuth

from portal_core.model.identity import OutputIdentity
from tests.util import verify_signature_auth, install_test_app


def test_call_peer_app_basic(peer_mock_requests, api_client):
	portal_identity = OutputIdentity(**api_client.get('public/meta/whoareyou').json())
	pubkey = PublicKey(portal_identity.public_key_pem)

	path = '/foo/bar'
	response = api_client.get(f'internal/call_peer/{peer_mock_requests.identity.short_id}/{path}')
	assert response.status_code == 200

	received_request = peer_mock_requests.mock.calls[0].request
	v = verify_signature_auth(received_request, pubkey)
	assert portal_identity.id.startswith(v.parameters['keyid'])
	assert received_request.path_url == path


def test_peer_auth(peer_mock_requests, api_client):
	peer = peer_mock_requests.identity
	peer_auth = HTTPSignatureAuth(
		signature_algorithm=algorithms.RSA_PSS_SHA512,
		key_id=peer.short_id,
		key=peer.private_key.encode(),
	)
	default_identity = api_client.get('protected/identities/default').json()

	with install_test_app():
		response = api_client.get(
			'internal/auth',
			auth=peer_auth,
			headers={'X-Forwarded-Host': 'myapp.myportal.org', 'X-Forwarded-Uri': '/peer'})
		assert response.status_code == status.HTTP_401_UNAUTHORIZED

		api_client.put('protected/peers', json={
			'id': peer.short_id,
			'name': 'peer',
		})

		response = api_client.get(
			'internal/auth',
			auth=peer_auth,
			headers={'X-Forwarded-Host': 'myapp.myportal.org', 'X-Forwarded-Uri': '/peer'})
		response.raise_for_status()
		assert response.headers['X-Ptl-Client-Type'] == 'peer'
		assert response.headers['X-Ptl-Client-Id'] == peer.short_id
		assert response.headers['X-Ptl-Client-Name'] == peer.name
