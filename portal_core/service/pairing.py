import logging
import random
import secrets
import string
from dataclasses import dataclass
from datetime import datetime, timedelta

import gconf
import jwt


STORE_KEY_JWT_SECRET = 'terminal_jwt_secret'
STORE_KEY_PAIRING_CODE = 'pairing_code'

log = logging.getLogger(__name__)


def make_pairing_code(deadline: int = None):
	pairing_code = PairingCode(
		code=(''.join(random.choices(string.digits, k=6))),
		created=datetime.now(),
		valid_until=datetime.now() + timedelta(
			seconds=deadline or gconf.get('terminal.pairing code deadline', default=600))
	)
	with persistence.key_value_store() as store:
		store[STORE_KEY_PAIRING_CODE] = pairing_code
	return pairing_code


def redeem_pairing_code(incoming_code: str):
	with persistence.key_value_store() as store:
		try:
			existing_pairing_code: service.PairingCode = store[STORE_KEY_PAIRING_CODE]
		except KeyError:
			raise InvalidPairingCode('no pairing code was issued yet')
		if existing_pairing_code.code != incoming_code:
			raise InvalidPairingCode(
				f'code ({incoming_code}) does not match existing code ({existing_pairing_code.code})')
		if datetime.now() > existing_pairing_code.valid_until:
			raise PairingCodeExpired(f'issued code ({existing_pairing_code.code}) is expired')
		else:
			del store[STORE_KEY_PAIRING_CODE]


def create_terminal_jwt(terminal_id, **kwargs) -> str:
	_ensure_jwt_secret()
	payload = {
		'sub': terminal_id,
		'iat': int(datetime.now().timestamp()),
		**kwargs
	}

	with persistence.key_value_store() as store:
		jwt_secret = store[STORE_KEY_JWT_SECRET]

	return jwt.encode(payload, jwt_secret, algorithm='HS256')


def verify_terminal_jwt(token: str):
	with persistence.key_value_store() as store:
		try:
			jwt_secret = store[STORE_KEY_JWT_SECRET]
		except KeyError as e:
			raise InvalidJwt from e

	bearer = 'Bearer '
	if token.startswith(bearer):
		token = token[len(bearer):]

	try:
		decoded_token = jwt.decode(token, jwt_secret, algorithms=['HS256'])
	except jwt.InvalidTokenError as e:
		raise InvalidJwt from e

	try:
		return persistence.find_terminal_by_id(decoded_token['sub'])
	except KeyError as e:
		raise InvalidJwt from e


@dataclass
class PairingCode:
	code: str
	created: datetime
	valid_until: datetime


def _ensure_jwt_secret():
	with persistence.key_value_store() as store:
		if STORE_KEY_JWT_SECRET not in store:
			jwt_secret = secrets.token_urlsafe(gconf.get('terminal.jwt secret length', default=64))
			store[STORE_KEY_JWT_SECRET] = jwt_secret


class InvalidPairingCode(Exception):
	pass


class PairingCodeExpired(Exception):
	pass


class InvalidJwt(Exception):
	pass
