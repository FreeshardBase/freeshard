import logging

from fastapi import APIRouter, Cookie
from pydantic import BaseModel

from portal_core.model.auth import AuthState
from portal_core.model.identity import OutputIdentity
from portal_core.service import pairing, identity

log = logging.getLogger(__name__)

router = APIRouter(
	prefix='/meta',
)


@router.get('/whoareyou', response_model=OutputIdentity)
def who_are_you():
	default_identity = identity.get_default_identity()
	return OutputIdentity(**default_identity.dict())


class OutputWhoAmI(BaseModel):
	type: AuthState.ClientType
	id: str = None
	name: str = None

	@classmethod
	def anonymous(cls):
		return cls(type=AuthState.ClientType.ANONYMOUS, id=None, name=None)


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
			type=AuthState.ClientType.TERMINAL,
			id=terminal.id,
			name=terminal.name,
		)
