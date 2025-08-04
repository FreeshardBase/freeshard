import pytest
from shard_core.service.crypto import PublicKey
from http_message_signatures import InvalidSignature
from httpx import AsyncClient

from shard_core.data_model.identity import Identity, OutputIdentity
from shard_core.data_model.profile import Profile
from tests import conftest
from tests.conftest import requires_test_env
from tests.util import verify_signature_auth


@requires_test_env("full")
async def test_call_management_api_verified(requests_mock, api_client: AsyncClient):
    identity = OutputIdentity(**(await api_client.get("public/meta/whoareyou")).json())
    pubkey = PublicKey(identity.public_key_pem)
    profile_response = await api_client.get("protected/management/profile")
    profile_response.raise_for_status()
    assert Profile.parse_obj(profile_response.json()) == Profile.from_shard(
        conftest.mock_shard
    )

    v = verify_signature_auth(requests_mock.calls[0].request, pubkey)
    assert identity.id.startswith(v.parameters["keyid"])


@requires_test_env("full")
async def test_call_management_api_fail_verify(requests_mock, api_client: AsyncClient):
    profile_response = await api_client.get("protected/management/profile")
    profile_response.raise_for_status()
    assert Profile.parse_obj(profile_response.json()) == Profile.from_shard(
        conftest.mock_shard
    )

    invalid_identity = Identity.create("invalid")
    with pytest.raises(InvalidSignature):
        verify_signature_auth(
            requests_mock.calls[0].request, invalid_identity.public_key
        )
