import io
import logging
import tarfile
from contextlib import suppress
from typing import List

from docker import DockerClient, errors as docker_errors
from fastapi import APIRouter, status, HTTPException
from fastapi.responses import Response
from tinydb import where, Query

import portal_core.service.app_store
from portal_core.database.database import apps_table
from portal_core.model.app_meta import InstalledApp, AppMeta
from portal_core.service import app_store

from portal_core.service.app_store import AppAlreadyInstalled

log = logging.getLogger(__name__)

router = APIRouter(
	prefix='/apps',
)


@router.get('', response_model=List[InstalledApp])
def list_all_apps():
	with apps_table() as apps:
		apps = [InstalledApp(**a) for a in apps.all()]
	docker_client = DockerClient(base_url='unix://var/run/docker.sock')
	containers = {c.name: c for c in docker_client.containers.list(all=True)}
	for app in apps:
		with suppress(KeyError):
			app.status = containers[app.name].status
	return list(apps)


@router.get('/{name}', response_model=InstalledApp)
def get_app(name: str):
	with apps_table() as apps:
		installed_app = apps.get(Query().name == name)
	if installed_app:
		return installed_app
	raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)


@router.get('/{name}/app.json', response_model=AppMeta)
def get_app_json(name: str):
	with apps_table() as apps:
		installed_app = apps.get(Query().name == name)
	if installed_app:
		return installed_app
	return app_store.get_store_app(name)


@router.delete('/{name}', status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def uninstall_app(name: str):
	with apps_table() as apps:
		apps.remove(where('name') == name)
	portal_core.service.app_store.write_traefik_dyn_config()


@router.post('/{name}', status_code=status.HTTP_201_CREATED)
async def install_app(name: str):
	try:
		await app_store.install_store_app(name)
	except AppAlreadyInstalled:
		raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f'App {name} is already installed')


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
