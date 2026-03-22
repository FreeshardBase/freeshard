from httpx import AsyncClient

from shard_core.data_model.identity import OutputIdentity
from shard_core.service.crypto import PublicKey


async def test_get_whoareyou(app_client: AsyncClient):
    default_identity = OutputIdentity.model_validate(
        (await app_client.get("protected/identities/default")).json()
    )
    whoareyou_response = await app_client.get("public/meta/whoareyou")
    whoareyou_response.raise_for_status()
    whoareyou = OutputIdentity.model_validate(whoareyou_response.json())
    assert whoareyou.domain[:6].lower() == default_identity.id[:6].lower()
    assert whoareyou.id == default_identity.id
    assert PublicKey(whoareyou.public_key_pem).to_hash_id() == whoareyou.id


async def test_get_whoami(app_client: AsyncClient):
    whoami = (await app_client.get("public/meta/whoami")).json()
    assert whoami["type"] == "anonymous"
