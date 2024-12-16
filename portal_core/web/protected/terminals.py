import logging
from datetime import datetime
from typing import List

from fastapi import APIRouter, status, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.exc import NoResultFound
from sqlmodel import select

from portal_core.database.database import session
from portal_core.database.models import Terminal
from portal_core.model.terminal import InputTerminal
from portal_core.service import pairing
from portal_core.service import terminal as terminal_service
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
	with session() as session_:
		return session_.exec(select(Terminal)).all()


@router.get('/id/{id_}')
def get_terminal_by_id(id_: str):
	try:
		return terminal_service.get_terminal_by_id(id_)
	except KeyError:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)


@router.get('/name/{name}', response_model=Terminal)
def get_terminal_by_name(name: str):
	with session() as session_:
		statement = select(Terminal).where(Terminal.name == name)
		try:
			return session_.exec(statement).one()
		except NoResultFound:
			raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)


@router.put('/id/{id_}')
def edit_terminal(id_: str, terminal: InputTerminal):
	with session() as session_:
		try:
			existing_terminal = session_.exec(select(Terminal).where(Terminal.id == id_)).one()
		except NoResultFound:
			raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
		existing_terminal.name = terminal.name
		existing_terminal.icon = terminal.icon
		session_.add(existing_terminal)
		session_.commit()
		on_terminals_update.send()


@router.delete('/id/{id_}', status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def delete_terminal_by_id(id_: str):
	with session() as session_:
		try:
			existing_terminal = session_.exec(select(Terminal).where(Terminal.id == id_)).one()
		except NoResultFound:
			raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
		session_.delete(existing_terminal)
		session_.commit()
		on_terminals_update.send()


@router.get('/pairing-code', response_model=PairingCode, status_code=status.HTTP_201_CREATED)
def new_pairing_code(deadline: int = None):
	pairing_code = pairing.make_pairing_code(deadline=deadline)
	log.info('created new terminal pairing code')
	return pairing_code
