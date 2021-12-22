import logging

from fastapi import APIRouter, HTTPException, status, Response
from pydantic import BaseModel

from identity_handler import service, persistence
from identity_handler.service import pubsub
from ..protected.terminals import Terminal

log = logging.getLogger(__name__)

router = APIRouter(
	prefix='/pair',
)


class InputTerminal(BaseModel):
	name: str
	description: str = None


@router.post('/terminal', status_code=status.HTTP_201_CREATED)
def add_terminal(code: str, terminal: InputTerminal, response: Response):
	try:
		service.redeem_pairing_code(code)
	except (KeyError, service.InvalidPairingCode, service.PairingCodeExpired) as e:
		log.info(e)
		raise HTTPException(status.HTTP_401_UNAUTHORIZED) from e

	try:
		new_terminal = persistence.add_terminal(
			terminal.name,
			terminal.description
		)
	except persistence.TerminalAlreadyExists as e:
		raise HTTPException(status.HTTP_409_CONFLICT) from e

	jwt = service.create_terminal_jwt(new_terminal.id)
	response.set_cookie('authorization', jwt,
		domain=service.get_own_domain(),
		secure=True, httponly=True, expires=60 * 60 * 24 * 356 * 10)
	pubsub.publish('terminal.add', new_terminal, as_=Terminal)
	log.info(f'added {new_terminal}')
