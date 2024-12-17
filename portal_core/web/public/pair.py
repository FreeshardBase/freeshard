import logging

from fastapi import APIRouter, HTTPException, status, Response
from sqlmodel import select
from portal_core.database.database import session
from portal_core.database.models import Terminal
from portal_core.model.terminal import InputTerminal
from portal_core.service import pairing
from portal_core.service.identity import get_default_identity
from portal_core.util.signals import async_on_first_terminal_add, on_terminals_update, on_terminal_add

log = logging.getLogger(__name__)

router = APIRouter(
	prefix='/pair',
)


@router.post('/terminal', status_code=status.HTTP_201_CREATED)
async def add_terminal(code: str, terminal: InputTerminal, response: Response):
	try:
		pairing.redeem_pairing_code(code)
	except (KeyError, pairing.InvalidPairingCode, pairing.PairingCodeExpired) as e:
		log.info(e)
		raise HTTPException(status.HTTP_401_UNAUTHORIZED) from e

	new_terminal = Terminal.create(terminal.name)
	with session() as session_:
		session_.add(new_terminal)
		session_.commit()

		session_.exec(select(Terminal)).all()
		is_first_terminal = len(session_.exec(select(Terminal)).all()) == 1

	default_identity = get_default_identity()

	jwt = pairing.create_terminal_jwt(new_terminal.id)
	response.set_cookie('authorization', jwt,
		domain=default_identity.domain,
		secure=True, httponly=True, expires=60 * 60 * 24 * 356 * 10)

	on_terminals_update.send()
	on_terminal_add.send(new_terminal)
	if is_first_terminal:
		await async_on_first_terminal_add.send_async(new_terminal)

	log.info(f'added {new_terminal}')
