import logging
from datetime import datetime
from typing import List

from fastapi import APIRouter, status, HTTPException
from pydantic import BaseModel
from tinydb import Query
from tinydb.table import Table

from portal_core.database.database import terminals_table
from portal_core.service import pairing
from portal_core.model.terminal import Terminal

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


@router.get('/name/{name}', response_model=Terminal)
def get_terminal_by_name(name: str):
	with terminals_table() as terminals:
		if t := terminals.get(Query().name == name):
			return t
		else:
			raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)


@router.delete('/id/{id_}', status_code=status.HTTP_204_NO_CONTENT)
def delete_terminal_by_id(id_: str):
	with terminals_table() as terminals:  # type: Table
		terminals.remove(Query().id == id_)


@router.get('/pairing-code', response_model=PairingCode, status_code=status.HTTP_201_CREATED)
def new_pairing_code(deadline: int = None):
	pairing_code = pairing.make_pairing_code(deadline=deadline)
	log.info('created new terminal pairing code')
	return pairing_code
