import logging
import random
import secrets
import string
from datetime import datetime, timedelta, timezone

import gconf
import jwt
from pydantic import BaseModel
from tinydb import Query

from shard_core.database import database
from shard_core.database.database import terminals_table
from shard_core.data_model.terminal import Terminal

STORE_KEY_JWT_SECRET = "terminal_jwt_secret"
STORE_KEY_PAIRING_CODE = "pairing_code"

log = logging.getLogger(__name__)


class PairingCode(BaseModel):
    code: str
    created: datetime
    valid_until: datetime


def make_pairing_code(deadline: int = None):
    now = datetime.now(timezone.utc)
    pairing_code = PairingCode(
        code=("".join(random.choices(string.digits, k=6))),
        created=now,
        valid_until=now
        + timedelta(
            seconds=deadline or gconf.get("terminal.pairing code deadline", default=600)
        ),
    )
    database.set_value(STORE_KEY_PAIRING_CODE, pairing_code.dict())
    return pairing_code


def redeem_pairing_code(incoming_code: str):
    try:
        existing_pairing_code = PairingCode(
            **database.get_value(STORE_KEY_PAIRING_CODE)
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
        database.remove_value(STORE_KEY_PAIRING_CODE)


def create_terminal_jwt(terminal_id, **kwargs) -> str:
    jwt_secret = _ensure_jwt_secret()
    payload = {
        "sub": terminal_id,
        "iat": int(datetime.now(timezone.utc).timestamp()),
        **kwargs,
    }
    return jwt.encode(payload, jwt_secret, algorithm="HS256")


def verify_terminal_jwt(token: str = None):
    if not token:
        raise InvalidJwt("Missing JWT")

    jwt_secret = _ensure_jwt_secret()

    bearer = "Bearer "
    if token.startswith(bearer):
        token = token[len(bearer) :]

    try:
        decoded_token = jwt.decode(token, jwt_secret, algorithms=["HS256"])
    except jwt.InvalidTokenError as e:
        raise InvalidJwt from e

    with terminals_table() as terminals:  # type: Table
        if terminal := terminals.get(Query().id == decoded_token["sub"]):
            return Terminal(**terminal)
        else:
            raise InvalidJwt


def _ensure_jwt_secret():
    try:
        database.get_value(STORE_KEY_JWT_SECRET)
    except KeyError:
        jwt_secret = secrets.token_urlsafe(
            gconf.get("terminal.jwt secret length", default=64)
        )
        database.set_value(STORE_KEY_JWT_SECRET, jwt_secret)
    return database.get_value(STORE_KEY_JWT_SECRET)


class InvalidPairingCode(Exception):
    pass


class PairingCodeExpired(Exception):
    pass


class InvalidJwt(Exception):
    pass
