import logging
from datetime import datetime
from typing import List

from fastapi import APIRouter, status, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from tinydb import Query

from portal_core.database.database import terminals_table
from portal_core.model.terminal import Terminal, InputTerminal
from portal_core.service import pairing
from portal_core.util.signals import on_terminals_update

log = logging.getLogger(__name__)

router = APIRouter(
	prefix='/terminals',
)


class PairingCode(BaseModel):
	code: str
	created: datetime
	valid_until: datetime


@router.get('', response_model=List[Terminal])
def list_all_terminals():
	with terminals_table() as terminals:  # type: Table
		return terminals.all()


@router.get('/id/{id_}')
def get_terminal_by_id(id_: str):
	with terminals_table() as terminals:
		if t := terminals.get(Query().id == id_):
			return t
		else:
			raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)


@router.get('/name/{name}', response_model=Terminal)
def get_terminal_by_name(name: str):
	with terminals_table() as terminals:
		if t := terminals.get(Query().name == name):
			return t
		else:
			raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)


@router.put('/id/{id_}')
async def edit_terminal(id_: str, terminal: InputTerminal):
	with terminals_table() as terminals:  # type: Table
		if t := terminals.get(Query().id == id_):
			existing_terminal = Terminal(**t)
			existing_terminal.name = terminal.name
			existing_terminal.icon = terminal.icon
			terminals.update(existing_terminal.dict(), Query().id == id_)
			await on_terminals_update.send_async()
		else:
			raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)


@router.delete('/id/{id_}', status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def delete_terminal_by_id(id_: str):
	with terminals_table() as terminals:  # type: Table
		terminals.remove(Query().id == id_)
	await on_terminals_update.send_async()


@router.get('/pairing-code', response_model=PairingCode, status_code=status.HTTP_201_CREATED)
def new_pairing_code(deadline: int = None):
	pairing_code = pairing.make_pairing_code(deadline=deadline)
	log.info('created new terminal pairing code')
	return pairing_code
