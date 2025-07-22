from shard_core.model.identity import OutputIdentity
from shard_core.service.crypto import PublicKey

from tests.conftest import requires_test_env
from tests.util import verify_signature_auth


@requires_test_env('full')
async def test_call_backend_from_app_basic(requests_mock, api_client):
	whoareyou = await api_client.get('public/meta/whoareyou')
	identity = OutputIdentity(**whoareyou.json())
	pubkey = PublicKey(identity.public_key_pem)

	path = '/api/shards/self'
	response = await api_client.get(f'internal/call_backend{path}')
	assert response.status_code == 200

	received_request = requests_mock.calls[0].request
	v = verify_signature_auth(received_request, pubkey)
	assert identity.id.startswith(v.parameters['keyid'])
	assert received_request.path_url == path
