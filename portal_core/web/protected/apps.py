import io
import logging
import mimetypes
from typing import List
import aiofiles

from fastapi import APIRouter, status, HTTPException, UploadFile
from fastapi.responses import Response, StreamingResponse
from tinydb import Query

from portal_core.database.database import installed_apps_table
from portal_core.model.app_meta import InstalledAppWithMeta, InstalledApp
from portal_core.service import app_installation
from portal_core.service.app_installation import AppAlreadyInstalled, AppNotInstalled
from portal_core.service.app_tools import get_installed_apps_path, get_app_metadata, MetadataNotFound, \
	enrich_installed_app_with_meta

log = logging.getLogger(__name__)

router = APIRouter(
	prefix='/apps',
)


@router.get('', response_model=List[InstalledAppWithMeta])
def list_all_apps():
	with installed_apps_table() as installed_apps:
		apps = [InstalledApp.parse_obj(app) for app in installed_apps.all()]
	return [enrich_installed_app_with_meta(app) for app in apps]


@router.post('', status_code=status.HTTP_201_CREATED)
async def install_custom_app(file: UploadFile):
	if not file.filename.endswith(".zip"):
		raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only zip files are supported")

	file_path = get_installed_apps_path() / file.filename[:-4] / file.filename
	file_path.parent.mkdir(parents=True, exist_ok=True)

	# Save the uploaded zip file to the server
	async with aiofiles.open(file_path, "wb") as f:
		while chunk := await file.read(1024):
			await f.write(chunk)

	# todo: Install the app


@router.get('/{name}', response_model=InstalledAppWithMeta)
def get_app(name: str):
	with installed_apps_table() as installed_apps:
		installed_app = installed_apps.get(Query().name == name)
	if installed_app:
		return enrich_installed_app_with_meta(InstalledApp.parse_obj(installed_app))
	raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)


@router.get('/{name}/icon')
def get_app_icon(name: str):
	try:
		app_meta = get_app_metadata(name)
	except MetadataNotFound:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f'App {name} is not installed')
	icon_filename = get_installed_apps_path() / name / app_meta.icon

	with open(icon_filename, 'rb') as icon_file:
		buffer = io.BytesIO(icon_file.read())
	return StreamingResponse(buffer, media_type=mimetypes.guess_type(icon_filename)[0])


@router.delete('/{name}', status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def uninstall_app(name: str):
	try:
		await app_installation.uninstall_app(name)
	except AppNotInstalled:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f'App {name} is not installed')


@router.post('/{name}', status_code=status.HTTP_201_CREATED)
async def install_app(name: str, branch: str = 'master'):
	try:
		await app_installation.install_store_app(name, store_branch=branch)
	except AppAlreadyInstalled:
		raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f'App {name} is already installed')
