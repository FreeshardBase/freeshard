import logging
from typing import Optional, List

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from tinydb import Query
from tinydb.table import Table

from portal_core.database import identities_table
from portal_core.model.identity import Identity

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


@router.get('/default', response_model=OutputIdentity)
def get_default_identity():
	return persistence.get_default_identity()


@router.get('/{name_prefix}', response_model=OutputIdentity)
def get_identity_by_name(name_prefix: str):
	return persistence.find_identity_by_name(name_prefix)


@router.post('/{name}/make-default', status_code=status.HTTP_204_NO_CONTENT)
def make_identity_default(name):
	i = persistence.find_identity_by_name(name)
	persistence.make_identity_default(i)
	pubsub.publish('identity.modify', i, as_=OutputIdentity)
	log.info(f'set as default {i}')
