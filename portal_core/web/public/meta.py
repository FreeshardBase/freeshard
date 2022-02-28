import logging

from fastapi import APIRouter, Cookie
from pydantic import BaseModel

from tinydb import Query

from portal_core.web.dependencies import AuthValues
from portal_core.database.database import identities_table
from portal_core.model.identity import Identity
from portal_core.service import pairing

log = logging.getLogger(__name__)

router = APIRouter(
	prefix='/meta',
)


class OutputWhoAreYou(BaseModel):
	status: str
	domain: str
	id: str
	public_key_pem: str


@router.get('/whoareyou', response_model=OutputWhoAreYou)
def who_are_you():
	with identities_table() as identities:
		default_identity = Identity(**identities.get(Query().is_default == True))
	return OutputWhoAreYou(
		status='OK',
		domain=default_identity.domain,
		id=default_identity.id,
		public_key_pem=default_identity.public_key_pem,
	)


class OutputWhoAmI(BaseModel):
	type: AuthValues.ClientType
	id: str = None
	name: str = None

	@classmethod
	def anonymous(cls):
		return cls(type=AuthValues.ClientType.ANONYMOUS, id=None, name=None)


@router.get('/whoami', response_model=OutputWhoAmI)
def who_am_i(authorization: str = Cookie(None)):
	if not authorization:
		return OutputWhoAmI.anonymous()

	try:
		terminal = pairing.verify_terminal_jwt(authorization)
	except pairing.InvalidJwt:
		return OutputWhoAmI.anonymous()
	else:
		return OutputWhoAmI(
			type=AuthValues.ClientType.TERMINAL,
			id=terminal.id,
			name=terminal.name,
		)
