import logging
from datetime import datetime
from typing import List

from fastapi import APIRouter, status
from pydantic import BaseModel

from identity_handler import persistence, service
from identity_handler.service import pubsub

log = logging.getLogger(__name__)

router = APIRouter(
	prefix='/terminals',
)


class Terminal(BaseModel):
	id: str
	name: str
	description: str = None

	class Config:
		orm_mode = True
		getter_dict = persistence.util.PeeweeGetterDict


class PairingCode(BaseModel):
	code: str
	created: datetime
	valid_until: datetime

	class Config:
		orm_mode = True


@router.get('', response_model=List[Terminal])
def list_all_terminals():
	return list(persistence.get_all_terminals())


@router.get('/name/{name}', response_model=Terminal)
def get_terminal_by_name(name: str):
	t = persistence.find_terminal_by_name(name)
	return t


@router.delete('/id/{id}', status_code=status.HTTP_204_NO_CONTENT)
def delete_terminal_by_id(id: str):
	deleted_terminal = persistence.delete_terminal_by_id(id)
	pubsub.publish('terminal.delete', deleted_terminal, as_=Terminal)
	log.info(f'deleted {deleted_terminal}')


@router.get('/pairing-code', response_model=PairingCode, status_code=status.HTTP_201_CREATED)
def new_pairing_code(deadline: int = None):
	pairing_code = service.make_pairing_code(deadline=deadline)
	pubsub.publish('pairing_code.new', '')
	log.info('created new terminal pairing code')
	return pairing_code
