import logging

import gconf

from shard_core.data_model.backend.shard_model import ShardDb
from shard_core.database import database
from shard_core.service.signed_call import signed_request

log = logging.getLogger(__name__)

STORE_KEY_FREESHARD_CONTROLLER_SHARED_KEY = "freeshard_controller_shared_key"


async def call_freeshard_controller(path: str, method: str = "GET", body: bytes = None):
    base_url = gconf.get("freeshard_controller.base_url")
    url = f"{base_url}/{path}"
    log.debug(f"call to {method} {url}")
    return await signed_request(method, url, data=body)


async def refresh_shared_secret():
    response = await call_freeshard_controller("api/shards/self")
    shard = ShardDb.validate(response.json())
    shared_secret = shard.shared_secret
    database.set_value(STORE_KEY_FREESHARD_CONTROLLER_SHARED_KEY, shared_secret)
    return shared_secret


async def validate_shared_secret(secret: str):
    if not isinstance(secret, str) or len(secret) < 8:
        raise SharedSecretInvalid

    try:
        expected_shared_secret = database.get_value(
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
