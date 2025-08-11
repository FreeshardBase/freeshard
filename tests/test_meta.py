from httpx import AsyncClient

from shard_core.data_model.identity import OutputIdentity
from shard_core.service.crypto import PublicKey
from tests.conftest import requires_test_env


@requires_test_env("full")
async def test_get_whoareyou(api_client: AsyncClient):
    default_identity = OutputIdentity.validate(
        (await api_client.get("protected/identities/default")).json()
    )
    whoareyou_response = await api_client.get("public/meta/whoareyou")
    whoareyou_response.raise_for_status()
    whoareyou = OutputIdentity.validate(whoareyou_response.json())
    assert whoareyou.domain[:6].lower() == default_identity.id[:6].lower()
    assert whoareyou.id == default_identity.id
    assert PublicKey(whoareyou.public_key_pem).to_hash_id() == whoareyou.id


@requires_test_env("full")
async def test_get_whoami(api_client: AsyncClient):
    whoami = (await api_client.get("public/meta/whoami")).json()
    assert whoami["type"] == "anonymous"
