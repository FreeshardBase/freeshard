import logging
from typing import List, Optional

from fastapi import APIRouter, status
from pydantic import BaseModel

from portal_core import service
from portal_core.model import StoreApp, StoreAppOverview

log = logging.getLogger(__name__)

router = APIRouter(
	prefix='/store',
	tags=['/protected/store'],
)


class AppOverview(BaseModel):
	name: str
	description: str
	is_installed: bool


@router.get('/apps', response_model=List[StoreAppOverview])
def get_apps():
	return service.get_store_apps()


@router.get('/apps/{name}', response_model=StoreApp)
def get_app_details(name: str):
	return service.get_store_app(name)


@router.post('/apps/{name}', status_code=status.HTTP_201_CREATED)
def install_app(name: str):
	service.install_store_app(name)


@router.post('/ref')
def switch_store_ref(ref: Optional[str] = None):
	"""
	Refresh the local app store at a certain ref of the underlying git repo.
	If ref is missing, use `master`.
	"""
	service.refresh_app_store(ref=ref)
