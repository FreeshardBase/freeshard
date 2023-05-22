import datetime
import logging
from typing import List, Optional

import gconf
from fastapi import APIRouter, status, HTTPException
from pydantic import BaseModel

from portal_core.model.app_meta import AppMeta
from portal_core.service import app_store
from portal_core.service.app_store import AppStoreRefreshError, AppStoreStatus, AppAlreadyInstalled

log = logging.getLogger(__name__)

router = APIRouter(
	prefix='/store',
	tags=['/protected/store'],
)


class AppOverview(BaseModel):
	name: str
	description: str
	is_installed: bool


@router.get('/apps', response_model=List[AppMeta])
def get_apps(refresh: bool = False):
	refresh_interval = gconf.get('apps.app_store.refresh_interval', default=600)
	refresh_threshold = datetime.datetime.utcnow() - datetime.timedelta(seconds=refresh_interval)
	current_status = app_store.get_app_store_status()
	if not current_status.last_update or current_status.last_update < refresh_threshold or refresh:
		app_store.refresh_app_store()
	return app_store.get_store_apps()


@router.post('/apps/{name}', status_code=status.HTTP_201_CREATED)
def install_app(name: str):
	try:
		app_store.install_store_app(name)
	except AppAlreadyInstalled:
		raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f'App {name} is already installed')


class StoreBranchIn(BaseModel):
	branch: str


@router.post('/branch')
def set_store_branch(branch: Optional[StoreBranchIn] = None):
	"""
	Set the local app store to certain branch of the underlying git repo.
	If branch is missing, use `master`.
	"""
	try:
		new_branch = branch.branch if branch else 'master'
		app_store.set_app_store_branch(new_branch)
		app_store.refresh_app_store()
	except AppStoreRefreshError:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f'No branch named {branch.branch}')


@router.get('/branch', response_model=AppStoreStatus)
def get_store_branch():
	return app_store.get_app_store_status()
