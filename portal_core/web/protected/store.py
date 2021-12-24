import logging
from typing import List, Optional

from fastapi import APIRouter, status
from pydantic import BaseModel

from portal_core.model.app import StoreApp, StoreAppOverview
from portal_core.service import app_store

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
	return app_store.get_store_apps()


@router.get('/apps/{name}', response_model=StoreApp)
def get_app_details(name: str):
	return app_store.get_store_app(name)


@router.post('/apps/{name}', status_code=status.HTTP_201_CREATED)
def install_app(name: str):
	app_store.install_store_app(name)


@router.post('/ref')
def switch_store_ref(ref: Optional[str] = None):
	"""
	Refresh the local app store at a certain ref of the underlying git repo.
	If ref is missing, use `master`.
	"""
	app_store.refresh_app_store(ref=ref)
