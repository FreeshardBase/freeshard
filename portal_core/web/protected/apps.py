import io
import logging
import mimetypes
from typing import List

from fastapi import APIRouter, status, HTTPException
from fastapi.responses import Response, StreamingResponse
from tinydb import Query

from portal_core.database.database import apps_table
from portal_core.model.app_meta import InstalledApp
from portal_core.service import app_installation

from portal_core.service.app_installation import AppAlreadyInstalled, AppNotInstalled

from portal_core.service.app_tools import get_installed_apps_path, get_app_metadata

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


@router.get('/{name}/icon')
def get_app_icon(name: str):
	app_meta = get_app_metadata(name)
	icon_filename = get_installed_apps_path() / name / app_meta.icon

	with open(icon_filename, 'rb') as icon_file:
		buffer = io.BytesIO(icon_file.read())
	return StreamingResponse(buffer, media_type=mimetypes.guess_type(icon_filename)[0])


@router.delete('/{name}', status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def uninstall_app(name: str):
	# todo: return early
	try:
		await app_installation.uninstall_app(name)
	except AppNotInstalled:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f'App {name} is not installed')


@router.post('/{name}', status_code=status.HTTP_201_CREATED)
async def install_app(name: str):
	# todo: return early
	try:
		await app_installation.install_store_app(name)
	except AppAlreadyInstalled:
		raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f'App {name} is already installed')
