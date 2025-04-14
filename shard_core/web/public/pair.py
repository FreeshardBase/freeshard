import logging

from fastapi import APIRouter, HTTPException, status, Response
from tinydb import Query

from shard_core.database.database import terminals_table, identities_table
from shard_core.model.identity import Identity
from shard_core.model.terminal import Terminal, InputTerminal
from shard_core.service import pairing
from shard_core.util.signals import async_on_first_terminal_add, on_terminals_update, on_terminal_add

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
	with terminals_table() as terminals:  # type: Table
		terminals.insert(new_terminal.dict())
		is_first_terminal = terminals.count(Query().noop()) == 1

	with identities_table() as identities:  # type: Table
		default_identity = Identity(**identities.get(Query().is_default == True))  # noqa: E712

	jwt = pairing.create_terminal_jwt(new_terminal.id)
	response.set_cookie('authorization', jwt,
		# We need to explicitly set the domain in order for the cookie to be valid for subdomains.
		domain=default_identity.domain,
		secure=True, httponly=True, expires=60 * 60 * 24 * 356 * 10)

	on_terminals_update.send()
	on_terminal_add.send(new_terminal)
	if is_first_terminal:
		await async_on_first_terminal_add.send_async(new_terminal)

	log.info(f'added {new_terminal}')
