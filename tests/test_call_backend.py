from shard_core.data_model.identity import OutputIdentity
from shard_core.service.crypto import PublicKey

from tests.conftest import requires_test_env
from tests.util import verify_signature_auth


@requires_test_env("full")
async def test_call_backend_from_app_basic(requests_mock, api_client):
    whoareyou = await api_client.get("public/meta/whoareyou")
    identity = OutputIdentity(**whoareyou.json())
    pubkey = PublicKey(identity.public_key_pem)

    path = "/api/shards/self"
    response = await api_client.get(f"internal/call_backend{path}")
    assert response.status_code == 200

    received_request = requests_mock.calls[0].request
    v = verify_signature_auth(received_request, pubkey)
    assert identity.id.startswith(v.parameters["keyid"])
    assert received_request.path_url == path


@requires_test_env("full")
async def test_call_backend_with_query_strings(requests_mock, api_client):
    params = {"param1": "foo", "param2": "bar"}
    path = "/api/foo"
    response = await api_client.get(f"internal/call_backend{path}", params=params)
    response.raise_for_status()

    received_request = [
        call.request
        for call in requests_mock.calls
        if call.request.path_url.startswith(path)
    ][0]
    assert received_request.params == params
