import logging
from mimetypes import guess_type
from pathlib import Path
from typing import List

from fastapi import APIRouter, HTTPException, status
from fastapi.datastructures import UploadFile
from fastapi.responses import Response
from tinydb import Query

from portal_core.database.database import identities_table
from portal_core.model.identity import Identity, OutputIdentity, InputIdentity
from portal_core.service import identity as identity_service
from portal_core.util.assets import put_asset

log = logging.getLogger(__name__)

router = APIRouter(
	prefix='/identities',
)


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
		return identities.get(Query().is_default == True)  # noqa: E712


@router.get('/{id}', response_model=OutputIdentity)
def get_identity_by_id(id):
	with identities_table() as identities:
		if i := identities.get(Query().id == id):
			return i
		else:
			raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)


@router.put('', response_model=OutputIdentity, status_code=status.HTTP_201_CREATED)
def put_identity(i: InputIdentity):
	with identities_table() as identities:  # type: Table
		if i.id:
			if identities.get(Query().id == i.id):
				identities.update(i.dict(exclude_unset=True), Query().id == i.id)
				return OutputIdentity(**identities.get(Query().id == i.id))
			else:
				raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
		else:
			new_identity = Identity.create(**i.dict(exclude_unset=True))
			identities.insert(new_identity.dict())
			log.info(f'added {new_identity}')
			return new_identity


@router.put('/{id}/avatar', status_code=status.HTTP_201_CREATED)
async def put_avatar(id: str, file: UploadFile):
	if not guess_type(file.filename)[0].startswith('image/'):
		raise HTTPException(
			status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
			detail='Avatar must be an image'
		)

	i = OutputIdentity.parse_obj(get_identity_by_id(id))
	file_extension = file.filename.split('.')[-1]
	file_path = Path('avatars') / f'{i.id}.{file_extension}'
	await put_asset(await file.read(), file_path, overwrite=True)


@router.post('/{id}/make-default', status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def make_identity_default(id):
	try:
		identity_service.make_default(id)
	except KeyError:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
