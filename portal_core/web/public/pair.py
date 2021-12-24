import logging

from fastapi import APIRouter, HTTPException, status, Response
from pydantic import BaseModel
from tinydb import Query
from tinydb.table import Table

from portal_core.database import terminals_table, identities_table
from portal_core.model.identity import Identity
from portal_core.model.terminal import Terminal
from portal_core.service import pairing

log = logging.getLogger(__name__)

router = APIRouter(
	prefix='/pair',
)


class InputTerminal(BaseModel):
	name: str


@router.post('/terminal', status_code=status.HTTP_201_CREATED)
def add_terminal(code: str, terminal: InputTerminal, response: Response):
	with terminals_table() as terminals:  # type: Table
		if terminals.get(Query().name == terminal.name):
			raise HTTPException(status.HTTP_409_CONFLICT)

	try:
		pairing.redeem_pairing_code(code)
	except (KeyError, pairing.InvalidPairingCode, pairing.PairingCodeExpired) as e:
		log.info(e)
		raise HTTPException(status.HTTP_401_UNAUTHORIZED) from e

	new_terminal = Terminal.create(terminal.name)
	with terminals_table() as terminals:  # type: Table
		terminals.insert(new_terminal.dict())

	with identities_table() as identities:  # type: Table
		default_identity = Identity(**identities.get(Query().is_default == True))

	jwt = pairing.create_terminal_jwt(new_terminal.id)
	response.set_cookie('authorization', jwt,
		domain=default_identity.domain,
		secure=True, httponly=True, expires=60 * 60 * 24 * 356 * 10)
	log.info(f'added {new_terminal}')
