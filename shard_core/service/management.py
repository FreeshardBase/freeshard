import logging

import gconf

from shard_core.database import database
from shard_core.service.signed_call import signed_request

log = logging.getLogger(__name__)

STORE_KEY_MANAGEMENT_SHARED_KEY = "management_shared_key"


async def call_management(path: str, method: str = "GET", body: bytes = None):
    api_url = gconf.get("management.api_url")
    url = f"{api_url}/{path}"
    log.debug(f"call to {method} {url}")
    return await signed_request(method, url, data=body)


async def refresh_shared_secret():
    response = await call_management("sharedSecret")
    shared_secret = response.json()["shared_secret"]
    database.set_value(STORE_KEY_MANAGEMENT_SHARED_KEY, shared_secret)
    return shared_secret


async def validate_shared_secret(secret: str):
    if not isinstance(secret, str) or len(secret) < 8:
        raise SharedSecretInvalid

    try:
        expected_shared_secret = database.get_value(STORE_KEY_MANAGEMENT_SHARED_KEY)
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
