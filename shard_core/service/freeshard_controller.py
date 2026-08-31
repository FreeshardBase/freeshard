import logging

from shard_core.data_model.backend.shard_model import ShardDb
from shard_core.database import database
from shard_core.settings import settings
from shard_core.service.signed_call import signed_request

log = logging.getLogger(__name__)

STORE_KEY_FREESHARD_CONTROLLER_SHARED_KEY = "freeshard_controller_shared_key"


async def call_freeshard_controller(path: str, method: str = "GET", body: bytes = None):
    base_url = settings().freeshard_controller.base_url
    url = f"{base_url}/{path}"
    log.debug(f"call to {method} {url}")
    return await signed_request(method, url, data=body)


async def post_json(path: str, payload: dict, method: str = "POST"):
    """Call the controller with a JSON body, declared as JSON.

    requests sends no Content-Type for a raw-bytes body, and the controller only
    parses those because it has strict_content_type switched off — a temporary
    concession it intends to withdraw (FreeshardBase/freeshard-controller#272).
    """
    base_url = settings().freeshard_controller.base_url
    url = f"{base_url}/{path}"
    log.debug(f"call to {method} {url}")
    return await signed_request(method, url, json=payload)


async def relay_email_to_owner(subject: str, body: list[str]):
    """Ask the controller to mail the shard's owner.

    The recipient is always the address the controller currently has on file;
    the shard cannot choose it. That is why a notification about an address
    change has to be sent before the change is mirrored back.
    """
    response = await post_json("api/email_relay", {"subject": subject, "body": body})
    response.raise_for_status()


async def send_verification_email(address: str, token: str):
    """Ask the controller to mail a confirmation link to an unconfirmed address.

    The controller owns the template and builds the link from the shard domain
    it already knows, so no shard-supplied URL is ever rendered into an email.
    """
    response = await post_json(
        "api/email_verification", {"address": address, "token": token}
    )
    response.raise_for_status()


async def set_owner_email(address: str | None):
    """Mirror a confirmed address to shards.owner_email on the controller."""
    response = await post_json(
        "api/shards/self/owner-email", {"address": address}, method="PUT"
    )
    response.raise_for_status()


async def refresh_shared_secret():
    response = await call_freeshard_controller("api/shards/self")
    shard = ShardDb.model_validate(response.json())
    shared_secret = shard.shared_secret
    await database.set_value(STORE_KEY_FREESHARD_CONTROLLER_SHARED_KEY, shared_secret)
    return shared_secret


async def validate_shared_secret(secret: str):
    if not isinstance(secret, str) or len(secret) < 8:
        raise SharedSecretInvalid

    try:
        expected_shared_secret = await database.get_value(
            STORE_KEY_FREESHARD_CONTROLLER_SHARED_KEY
        )
    except KeyError:
        expected_shared_secret = await refresh_shared_secret()
        if secret != expected_shared_secret:
            raise SharedSecretInvalid
    else:
        if secret != expected_shared_secret:
            expected_shared_secret = await refresh_shared_secret()
            if secret != expected_shared_secret:
                raise SharedSecretInvalid


class SharedSecretInvalid(Exception):
    pass
