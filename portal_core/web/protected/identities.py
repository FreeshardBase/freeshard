import logging
from typing import Optional, List

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import Response
from pydantic import BaseModel
from tinydb import Query
from tinydb.table import Table

from portal_core.database.database import identities_table
from portal_core.model.identity import Identity
from portal_core.service import identity as identity_service

log = logging.getLogger(__name__)

router = APIRouter(
	prefix='/identities',
)


class OutputIdentity(BaseModel):
	id: str
	name: str
	description: Optional[str]
	is_default: bool
	public_key_pem: str


class InputIdentity(BaseModel):
	name: str
	description: Optional[str] = ''


@router.get('', response_model=List[OutputIdentity])
def list_all_identities(name: str = None):
	with identities_table() as identities:  # type: Table
		if name:
			return identities.search(Query().name.search(name))
		else:
			return identities.all()


@router.get('/default', response_model=OutputIdentity)
def get_default_identity():
	with identities_table() as identities:
		return identities.get(Query().is_default == True)


@router.get('/{name}', response_model=OutputIdentity)
def get_identity_by_name(name):
	with identities_table() as identities:
		if i := identities.get(Query().name == name):
			return i
		else:
			raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)


@router.post('', response_model=OutputIdentity, status_code=status.HTTP_201_CREATED)
def add_identity(i: InputIdentity):
	with identities_table() as identities:  # type: Table
		if identities.get(Query().name == i.name):
			raise HTTPException(status_code=status.HTTP_409_CONFLICT)
		else:
			new_identity = Identity.create(i.name, i.description)
			identities.insert(new_identity.dict())
			log.info(f'added {new_identity}')
			return new_identity


@router.post('/{name}/make-default', status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def make_identity_default(name):
	try:
		identity_service.make_default(name)
	except KeyError:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
