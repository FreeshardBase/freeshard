import logging
import random
import secrets
import string
from datetime import datetime, timedelta, timezone

import gconf
import jwt
from pydantic import BaseModel

from portal_core.database.models import Terminal
from portal_core.old_database import database as old_database

from portal_core.service.terminal import get_terminal_by_id

STORE_KEY_JWT_SECRET = 'terminal_jwt_secret'
STORE_KEY_PAIRING_CODE = 'pairing_code'

log = logging.getLogger(__name__)


class PairingCode(BaseModel):
	code: str
	created: datetime
	valid_until: datetime


def make_pairing_code(deadline: int = None):
	now = datetime.now(timezone.utc)
	pairing_code = PairingCode(
		code=(''.join(random.choices(string.digits, k=6))),
		created=now,
		valid_until=now + timedelta(
			seconds=deadline or gconf.get('terminal.pairing code deadline', default=600))
	)
	old_database.set_value(STORE_KEY_PAIRING_CODE, pairing_code.dict())
	return pairing_code


def redeem_pairing_code(incoming_code: str):
	try:
		existing_pairing_code = PairingCode(**old_database.get_value(STORE_KEY_PAIRING_CODE))
	except KeyError:
		raise InvalidPairingCode('no pairing code was issued yet')
	if existing_pairing_code.code != incoming_code:
		raise InvalidPairingCode(
			f'code ({incoming_code}) does not match existing code ({existing_pairing_code.code})')
	if datetime.now(timezone.utc) > existing_pairing_code.valid_until:
		raise PairingCodeExpired(f'issued code ({existing_pairing_code.code}) is expired')
	else:
		old_database.remove_value(STORE_KEY_PAIRING_CODE)


def create_terminal_jwt(terminal_id, **kwargs) -> str:
	jwt_secret = _ensure_jwt_secret()
	payload = {
		'sub': terminal_id,
		'iat': int(datetime.now(timezone.utc).timestamp()),
		**kwargs
	}
	return jwt.encode(payload, jwt_secret, algorithm='HS256')


def verify_terminal_jwt(token: str = None) -> Terminal:
	if not token:
		raise InvalidJwt('Missing JWT')

	jwt_secret = _ensure_jwt_secret()

	bearer = 'Bearer '
	if token.startswith(bearer):
		token = token[len(bearer):]

	try:
		decoded_token = jwt.decode(token, jwt_secret, algorithms=['HS256'])
	except jwt.InvalidTokenError as e:
		raise InvalidJwt from e

	try:
		return get_terminal_by_id(decoded_token['sub'])
	except KeyError as e:
		raise InvalidJwt from e


def _ensure_jwt_secret():
	try:
		old_database.get_value(STORE_KEY_JWT_SECRET)
	except KeyError:
		jwt_secret = secrets.token_urlsafe(gconf.get('terminal.jwt secret length', default=64))
		old_database.set_value(STORE_KEY_JWT_SECRET, jwt_secret)
	return old_database.get_value(STORE_KEY_JWT_SECRET)


class InvalidPairingCode(Exception):
	pass


class PairingCodeExpired(Exception):
	pass


class InvalidJwt(Exception):
	pass
