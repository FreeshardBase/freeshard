import json
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


async def relay_email_to_owner(subject: str, body: list[str]):
    """Ask the controller to mail the shard's owner.

    The recipient is always the address the controller currently has on file;
    the shard cannot choose it. That is why a notification about an address
    change has to be sent before the change is mirrored back.
    """
    response = await call_freeshard_controller(
        "api/email_relay",
        method="POST",
        body=json.dumps({"subject": subject, "body": body}).encode(),
    )
    response.raise_for_status()


async def send_verification_email(address: str, token: str):
    """Ask the controller to mail a confirmation link to an unconfirmed address.

    The controller owns the template and builds the link from the shard domain
    it already knows, so no shard-supplied URL is ever rendered into an email.
    """
    response = await call_freeshard_controller(
        "api/email_verification",
        method="POST",
        body=json.dumps({"address": address, "token": token}).encode(),
    )
    response.raise_for_status()


async def set_owner_email(address: str | None):
    """Mirror a confirmed address to shards.owner_email on the controller."""
    response = await call_freeshard_controller(
        "api/shards/self/owner-email",
        method="PUT",
        body=json.dumps({"address": address}).encode(),
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
