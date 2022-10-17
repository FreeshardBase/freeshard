from common_py.crypto import PublicKey

from portal_core.model.identity import OutputIdentity
from tests.util import verify_signature_auth


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
