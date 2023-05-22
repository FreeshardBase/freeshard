import contextlib
import io
import json
import logging
import shutil
import tarfile
import datetime
from pathlib import Path

from azure.storage.blob.aio import ContainerClient
from typing import Iterable, List, Optional, Set

import gconf
from gitlab import Gitlab, GitlabListError
from gitlab.v4.objects import ProjectBranch
from pydantic import BaseModel
from tinydb import Query
from tinydb.table import Table

from portal_core.database.database import apps_table
from portal_core.model.app_meta import AppMeta, InstalledApp, InstallationReason, Status
from . import app_infra
from ..database import database

log = logging.getLogger(__name__)

STORE_KEY_CURRENT_APP_STORE_BRANCH = 'current_app_store_branch'


class AppStoreStatus(BaseModel):
	current_branch: str
	commit_id: str
	last_update: Optional[datetime.datetime]


def get_store_apps() -> Iterable[AppMeta]:
	sync_dir = Path(gconf.get('path_root')) / 'core' / 'appstore'
	for app_dir in sync_dir.iterdir():
		yield get_store_app(app_dir.name)


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
		store_branch: Optional[str] = 'master',
):
	with apps_table() as apps:  # type: Table
		if apps.contains(Query().name == name):
			raise AppAlreadyInstalled(name)
		apps.insert(InstalledApp(
			name=name,
			installation_reason=installation_reason,
			status=Status.INSTALLING,
			from_branch=store_branch,
		).dict())

	installed_apps_path = Path(gconf.get('path_root')) / 'core' / 'installed_apps'
	await download_azure_blob_directory(
		f'{store_branch}/all_apps/{name}',
		installed_apps_path / name,
	)




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


def set_app_store_branch(branch_name: str):
	with _get_gitlab_apps_project() as apps_project:
		available_branches: List[ProjectBranch] = apps_project.branches.list()

	try:
		branch = next(b for b in available_branches if b.name == branch_name)
	except StopIteration:
		raise AppStoreRefreshError(f'Unknown branch: {branch_name}')

	app_store_status = AppStoreStatus(
		current_branch=branch.name,
		commit_id=branch.commit['id'],
	)

	database.set_value(STORE_KEY_CURRENT_APP_STORE_BRANCH, app_store_status.dict())


def get_app_store_status() -> AppStoreStatus:
	return AppStoreStatus.parse_obj(database.get_value(STORE_KEY_CURRENT_APP_STORE_BRANCH))


def refresh_app_store():
	try:
		app_store_status = get_app_store_status()
	except KeyError:
		set_app_store_branch('master')
	else:
		set_app_store_branch(app_store_status.current_branch)

	ref = get_app_store_status().commit_id
	log.debug(f'refreshing app store with ref {ref}')
	fs_sync_dir = Path(gconf.get('path_root')) / 'core' / 'appstore'

	with _get_gitlab_apps_project() as apps_project:
		try:
			archive = tarfile.open(fileobj=io.BytesIO(apps_project.repository_archive(sha=ref)))
		except GitlabListError as e:
			log.error(f'Error during refreshing app store with ref {ref}: {e.error_message}')
			raise AppStoreRefreshError from e

	if fs_sync_dir.exists():
		shutil.rmtree(fs_sync_dir)

	archive_root = Path(archive.getnames()[0])
	archive_apps = archive_root / 'apps'
	for member in archive.getmembers():
		if member.name.startswith(str(archive_apps)) and member.name != str(archive_apps):
			fs_file = fs_sync_dir / Path(member.name).relative_to(archive_apps)
			if member.isdir():
				fs_file.mkdir(exist_ok=True, parents=True)
			else:
				with open(fs_file, 'wb') as f:
					if data := archive.extractfile(member):
						f.write(data.read())

	with database.global_db_lock:
		current_status = get_app_store_status()
		if current_status.commit_id != ref:
			log.error(
				f'Race Condition: commit_id changed from {ref} to {current_status.commit_id}'
				f' during app store refresh')
		else:
			current_status.last_update = datetime.datetime.utcnow()
			database.set_value(STORE_KEY_CURRENT_APP_STORE_BRANCH, current_status.dict())


@contextlib.contextmanager
def _get_gitlab_apps_project():
	apps_project = Gitlab('https://gitlab.com').projects.get(gconf.get('apps.app_store.project_id'))
	yield apps_project


class AppStoreRefreshError(Exception):
	pass


def refresh_init_apps():
	configured_init_apps = set(gconf.get('apps.initial_apps'))
	installed_apps = get_installed_apps()

	for app_name in configured_init_apps - installed_apps:
		install_store_app(app_name, InstallationReason.CONFIG)


def get_installed_apps() -> Set[str]:
	installed_apps_path = Path(gconf.get('path_root')) / 'core' / 'installed_apps'
	installed_apps = {p.name for p in installed_apps_path.iterdir()}
	return installed_apps
