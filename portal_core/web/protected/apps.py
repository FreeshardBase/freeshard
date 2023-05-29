import logging
from typing import List

from fastapi import APIRouter, status, HTTPException
from fastapi.responses import Response
from tinydb import Query

from portal_core.database.database import apps_table
from portal_core.model.app_meta import InstalledApp
from portal_core.service import app_store

from portal_core.service.app_store import AppAlreadyInstalled, AppNotInstalled

log = logging.getLogger(__name__)

router = APIRouter(
	prefix='/apps',
)


@router.get('', response_model=List[InstalledApp])
def list_all_apps():
	with apps_table() as apps:
		return apps.all()


@router.get('/{name}', response_model=InstalledApp)
def get_app(name: str):
	with apps_table() as apps:
		installed_app = apps.get(Query().name == name)
	if installed_app:
		return installed_app
	raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)


@router.delete('/{name}', status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def uninstall_app(name: str):
	# todo: return early
	try:
		await app_store.uninstall_app(name)
	except AppNotInstalled:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f'App {name} is not installed')


@router.post('/{name}', status_code=status.HTTP_201_CREATED)
async def install_app(name: str):
	# todo: return early
	try:
		await app_store.install_store_app(name)
	except AppAlreadyInstalled:
		raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f'App {name} is already installed')
