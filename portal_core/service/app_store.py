import asyncio
import contextlib
import io
import json
import logging
import shutil
import tarfile
from tinydb.table import Table
import datetime
import threading
from pathlib import Path

import jinja2
import pydantic
import yaml

from azure.storage.blob.aio import ContainerClient
from typing import Iterable, Optional, Set

import gconf
from gitlab import Gitlab, GitlabListError
from pydantic import BaseModel
from tinydb import Query

from portal_core.database.database import apps_table, identities_table
from portal_core.model.app_meta import AppMeta, InstalledApp, InstallationReason, Status
from portal_core.service.traefik_dynamic_config import compile_config, AppInfo
from .. import Identity
from ..database import database
from ..model.identity import SafeIdentity

log = logging.getLogger(__name__)

install_lock = threading.RLock()


class AppStoreStatus(BaseModel):
	current_branch: str
	commit_id: str
	last_update: Optional[datetime.datetime]


def get_store_app(name) -> AppMeta:
	sync_dir = Path(gconf.get('path_root')) / 'core' / 'appstore'
	app_dir = sync_dir / name
	if not app_dir.exists():
		raise KeyError(f'no app named {name}')
	with open(app_dir / 'app.json') as f:
		app = json.load(f)
		assert (a := app['name']) == (d := app_dir.name), f'app with name {a} in directory with name {d}'
		return AppMeta.parse_obj(app)


async def install_store_app(
		name: str,
		installation_reason: InstallationReason = InstallationReason.STORE,
		store_branch: Optional[str] = 'feature-docker-compose',  # todo: change back to master
):
	with apps_table() as apps:  # type: Table
		if apps.contains(Query().name == name):
			raise AppAlreadyInstalled(name)
		installed_app = InstalledApp(
			name=name,
			installation_reason=installation_reason,
			status=Status.INSTALLING,
			from_branch=store_branch,
		)
		apps.insert(installed_app.dict())

	with install_lock:
		await download_azure_blob_directory(
			f'{store_branch}/all_apps/{name}',
			get_installed_apps_path() / name,
		)

		write_traefik_dyn_config()

		await render_docker_compose_template(installed_app)

		pull_process = await asyncio.create_subprocess_exec(
			'docker-compose', 'pull',
			cwd=get_installed_apps_path() / name,
			stdout=asyncio.subprocess.PIPE,
			stderr=asyncio.subprocess.PIPE)
		await asyncio.wait_for(pull_process.wait(), timeout=gconf.get('apps.app_store.pull_timeout'))

		installed_app.status = Status.STOPPED
		with apps_table() as apps:  # type: Table
			apps.update(installed_app.dict(), Query().name == name)


def get_installed_apps_path() -> Path:
	return Path(gconf.get('path_root')) / 'core' / 'installed_apps'


class AppAlreadyInstalled(Exception):
	pass


async def download_azure_blob_directory(directory_name: str, target_dir: Path):
	async with ContainerClient(
			account_url=gconf.get('apps.app_store.base_url'),
			container_name=gconf.get('apps.app_store.container_name'),
	) as container_client:

		directory_name = directory_name.rstrip('/')
		async for blob in container_client.list_blobs(name_starts_with=directory_name):
			if blob.name.endswith('/'):
				continue
			target_file = target_dir / blob.name[len(directory_name) + 1:]
			target_file.parent.mkdir(exist_ok=True, parents=True)
			with open(target_file, 'wb') as f:
				download_blob = await container_client.download_blob(blob)
				f.write(await download_blob.readall())


async def render_docker_compose_template(app: InstalledApp):
	fs = {
		'app_data': Path(gconf.get('path_root')) / 'user_data' / 'app_data' / app.name,
		'shared_documents': Path(gconf.get('path_root')) / 'user_data' / 'shared' / 'documents',
		'shared_media': Path(gconf.get('path_root')) / 'user_data' / 'shared' / 'media',
		'shared_music': Path(gconf.get('path_root')) / 'user_data' / 'shared' / 'music',
	}

	with identities_table() as identities:
		default_identity = Identity(**identities.get(Query().is_default == True))  # noqa: E712
	portal = SafeIdentity(**default_identity.dict())

	app_dir = get_installed_apps_path() / app.name
	template = jinja2.Template((app_dir / 'docker-compose.yml.template').read_text())
	(app_dir / 'docker-compose.yml').write_text(template.render(
		fs=fs, portal=portal,
	))


async def refresh_init_apps():
	configured_init_apps = set(gconf.get('apps.initial_apps'))
	installed_apps = get_installed_apps()

	for app_name in configured_init_apps - installed_apps:
		await install_store_app(app_name, InstallationReason.CONFIG)


def get_installed_apps() -> Set[str]:
	installed_apps_path = Path(gconf.get('path_root')) / 'core' / 'installed_apps'
	installed_apps_path.mkdir(exist_ok=True, parents=True)
	installed_apps = {p.name for p in installed_apps_path.iterdir()}
	return installed_apps


def write_traefik_dyn_config():
	with apps_table() as apps:
		apps = [InstalledApp(**a) for a in apps.all()]
	app_infos = [AppInfo(get_app_metadata(a.name), installed_app=a) for a in apps]

	with identities_table() as identities:
		default_identity = Identity(**identities.get(Query().is_default == True))  # noqa: E712
	portal = SafeIdentity(**default_identity.dict())

	traefik_dyn_filename = Path(gconf.get('path_root')) / 'core' / 'traefik_dyn' / 'traefik_dyn.yml'
	write_to_yaml(compile_config(app_infos, portal), traefik_dyn_filename)


def write_to_yaml(spec: pydantic.BaseModel, output_path: Path):
	output_path.parent.mkdir(exist_ok=True, parents=True)
	with open(output_path, 'w') as f:
		f.write('# == DO NOT MODIFY ==\n# this file is auto-generated\n\n')
		f.write(yaml.dump(spec.dict(exclude_none=True)))


class AppNotInstalled(Exception):
	pass


def get_app_metadata(app_name: str) -> AppMeta:
	app_path = get_installed_apps_path() / app_name
	if not app_path.exists():
		raise AppNotInstalled(app_name)
	with open(app_path / 'app.json') as f:
		return AppMeta(**json.load(f))
