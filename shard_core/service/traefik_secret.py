import logging
import secrets

from fastapi import Header, HTTPException, status

from shard_core.database import database

log = logging.getLogger(__name__)

STORE_KEY_TRAEFIK_SECRET = "traefik_secret"
HEADER_NAME = "X-Ptl-Traefik-Secret"
_SECRET_LENGTH = 64


async def ensure_traefik_secret() -> str:
    try:
        return await database.get_value(STORE_KEY_TRAEFIK_SECRET)
    except KeyError:
        secret = secrets.token_urlsafe(_SECRET_LENGTH)
        await database.set_value(STORE_KEY_TRAEFIK_SECRET, secret)
        log.info("Generated new Traefik verification secret")
        return secret


async def get_traefik_secret() -> str:
    return await database.get_value(STORE_KEY_TRAEFIK_SECRET)


async def verify_traefik_secret(x_ptl_traefik_secret: str = Header(None)):
    try:
        expected = await get_traefik_secret()
    except KeyError:
        log.error("Traefik verification secret missing from kv_store")
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR)

    if not x_ptl_traefik_secret or not secrets.compare_digest(
        x_ptl_traefik_secret, expected
    ):
        log.warning("rejected request that did not traverse Traefik")
        raise HTTPException(status.HTTP_403_FORBIDDEN)
