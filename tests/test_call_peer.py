from common_py.crypto import PublicKey

from portal_core.model.identity import OutputIdentity
from tests.util import verify_signature_auth


def test_call_peer_app_basic(peer_mock_requests, api_client):
	portal_identity = OutputIdentity(**api_client.get('public/meta/whoareyou').json())
	pubkey = PublicKey(portal_identity.public_key_pem)

	path = 'foo'
	response = api_client.get(f'internal/call_peer/{peer_mock_requests.identity.short_id}/{path}')
	assert response.status_code == 200

	v = verify_signature_auth(peer_mock_requests.app.calls[0].request, pubkey)
	assert portal_identity.id.startswith(v.parameters['keyid'])
