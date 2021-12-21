import io
import logging
import mimetypes
import re
import tarfile
from contextlib import suppress
from pathlib import Path
from typing import List

import gconf
from docker import DockerClient, errors as docker_errors
from fastapi import APIRouter, status, HTTPException
from fastapi.responses import StreamingResponse
from tinydb import where

from portal_core import service
from portal_core.database import get_db
from portal_core.model import InstallationReason, InstalledApp, App

log = logging.getLogger(__name__)

router = APIRouter(
	prefix='/apps',
)


@router.get('', response_model=List[InstalledApp])
def list_all_apps():
	with get_db() as db:
		apps = [InstalledApp(**a) for a in db.table('apps').all()]
	docker_client = DockerClient(base_url='unix://var/run/docker.sock')
	containers = {c.name: c for c in docker_client.containers.list(all=True)}
	for app in apps:
		with suppress(KeyError):
			app.status = containers[app.name].status
	return list(apps)


@router.get('/{name}/icon')
def get_app_icon(name: str):
	matcher = re.compile(r'^icon\..+$')

	app_repo = Path(gconf.get('apps.app_store.sync_dir')) / name
	if app_repo.exists() and app_repo.is_dir():
		try:
			icon_filename = [f for f in app_repo.iterdir() if matcher.match(f.name)][0]
		except IndexError:
			pass
		else:
			with open(icon_filename, 'rb') as icon_file:
				buffer = io.BytesIO(icon_file.read())
			return StreamingResponse(buffer, media_type=mimetypes.guess_type(icon_filename)[0])

	else:
		try:
			tar = _get_metadata_tar(name)
		except docker_errors.NotFound:
			raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f'No icon for app named {name}')
		try:
			icon_filename = [n for n in tar.getnames() if matcher.match(n)][0]
		except IndexError:
			pass
		else:
			return StreamingResponse(tar.extractfile(icon_filename), media_type=mimetypes.guess_type(icon_filename)[0])

	raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f'No icon for app named {name}')


@router.post('', status_code=status.HTTP_201_CREATED)
def install_app(input_app: App):
	with get_db() as db:
		db.table('apps').insert({
			**input_app.dict(),
			'reason': InstallationReason.CUSTOM,
		})
		service.refresh_docker_compose()


@router.delete('/{name}', status_code=status.HTTP_204_NO_CONTENT)
def uninstall_app(name: str):
	with get_db() as db:
		db.table('apps').remove(where('name') == name)
	service.refresh_docker_compose()


def _get_metadata_tar(name) -> tarfile.TarFile:
	docker_client = DockerClient(base_url='unix://var/run/docker.sock')
	try:
		container = docker_client.containers.get(name)
	except docker_errors.NotFound as e:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from e
	bits, _ = container.get_archive('/portal_meta/icon.svg')
	f = io.BytesIO()
	for chunk in bits:
		f.write(chunk)
	f.seek(0)
	return tarfile.open(fileobj=f)
