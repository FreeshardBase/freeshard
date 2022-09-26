import logging

import gconf
from fastapi import APIRouter, Cookie
from pydantic import BaseModel

from portal_core.service import pairing, identity
from portal_core.service.signed_call import signed_request
from portal_core.web.dependencies import AuthValues
from portal_core.model.profile import Profile

log = logging.getLogger(__name__)

router = APIRouter(
	prefix='/meta',
)


class OutputWhoAreYou(BaseModel):
	status: str
	domain: str
	id: str
	public_key_pem: str

	@property
	def short_id(self):
		return self.id[:6]


@router.get('/whoareyou', response_model=OutputWhoAreYou)
def who_are_you():
	default_identity = identity.get_default_identity()
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


@router.get('/profile', response_model=Profile)
def profile():
	api_url = gconf.get('management.api_url')
	url = f'{api_url}/profile'
	log.debug(f'Getting profile from {url}')
	response = signed_request('GET', url)
	log.debug(f'profile response status: {response.status_code}')
	response.raise_for_status()
	return Profile(**response.json())
