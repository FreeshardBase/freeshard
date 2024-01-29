from portal_core.model.identity import OutputIdentity
from common_py.crypto import PublicKey
from tests.util import verify_signature_auth


async def test_call_backend_from_app_basic(requests_mock, api_client):
	whoareyou = await api_client.get('public/meta/whoareyou')
	portal_identity = OutputIdentity(**whoareyou.json())
	pubkey = PublicKey(portal_identity.public_key_pem)

	path = '/api/portals/self'
	response = await api_client.get(f'internal/call_backend{path}')
	assert response.status_code == 200

	received_request = requests_mock.calls[0].request
	v = verify_signature_auth(received_request, pubkey)
	assert portal_identity.id.startswith(v.parameters['keyid'])
	assert received_request.path_url == path
