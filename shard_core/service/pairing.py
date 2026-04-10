import logging
import random
import secrets
import string
from datetime import datetime, timedelta, timezone

import jwt
from pydantic import BaseModel

from shard_core.database import database
from shard_core.database.connection import db_conn
from shard_core.database import terminals as db_terminals
from shard_core.settings import settings
from shard_core.data_model.terminal import Terminal

STORE_KEY_JWT_SECRET = "terminal_jwt_secret"
STORE_KEY_PAIRING_CODE = "pairing_code"

log = logging.getLogger(__name__)


class PairingCode(BaseModel):
    code: str
    created: datetime
    valid_until: datetime


async def make_pairing_code(deadline: int = None):
    now = datetime.now(timezone.utc)
    pairing_code = PairingCode(
        code=("".join(random.choices(string.digits, k=6))),
        created=now,
        valid_until=now
        + timedelta(seconds=deadline or settings().terminal.pairing_code_deadline),
    )
    await database.set_value(STORE_KEY_PAIRING_CODE, pairing_code.model_dump())
    return pairing_code


async def redeem_pairing_code(incoming_code: str):
    try:
        existing_pairing_code = PairingCode(
            **await database.get_value(STORE_KEY_PAIRING_CODE)
        )
    except KeyError:
        raise InvalidPairingCode("no pairing code was issued yet")
    if existing_pairing_code.code != incoming_code:
        raise InvalidPairingCode(
            f"code ({incoming_code}) does not match existing code ({existing_pairing_code.code})"
        )
    if datetime.now(timezone.utc) > existing_pairing_code.valid_until:
        raise PairingCodeExpired(
            f"issued code ({existing_pairing_code.code}) is expired"
        )
    else:
        await database.remove_value(STORE_KEY_PAIRING_CODE)


async def create_terminal_jwt(terminal_id, **kwargs) -> str:
    jwt_secret = await _ensure_jwt_secret()
    payload = {
        "sub": terminal_id,
        "iat": int(datetime.now(timezone.utc).timestamp()),
        **kwargs,
    }
    return jwt.encode(payload, jwt_secret, algorithm="HS256")


async def verify_terminal_jwt(token: str = None):
    if not token:
        raise InvalidJwt("Missing JWT")

    jwt_secret = await _ensure_jwt_secret()

    bearer = "Bearer "
    if token.startswith(bearer):
        token = token[len(bearer) :]

    try:
        decoded_token = jwt.decode(token, jwt_secret, algorithms=["HS256"])
    except jwt.InvalidTokenError as e:
        raise InvalidJwt from e

    async with db_conn() as conn:
        terminal = await db_terminals.get_by_id(conn, decoded_token["sub"])
        if terminal:
            return Terminal(**terminal)
        else:
            raise InvalidJwt


async def _ensure_jwt_secret():
    try:
        return await database.get_value(STORE_KEY_JWT_SECRET)
    except KeyError:
        jwt_secret = secrets.token_urlsafe(settings().terminal.jwt_secret_length)
        await database.set_value(STORE_KEY_JWT_SECRET, jwt_secret)
        return jwt_secret


class InvalidPairingCode(Exception):
    pass


class PairingCodeExpired(Exception):
    pass


class InvalidJwt(Exception):
    pass
