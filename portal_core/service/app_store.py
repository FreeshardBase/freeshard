import io
import json
import logging
import shutil
import tarfile
from pathlib import Path
from typing import Iterable

import gconf
from gitlab import Gitlab
from tinydb import where

from portal_core.database import get_db
from portal_core.model import StoreApp, InstallationReason, AppToInstall
from . import compose

log = logging.getLogger(__name__)


def get_store_apps() -> Iterable[StoreApp]:
	sync_dir = Path(gconf.get('apps.app_store.sync_dir'))
	for app_dir in sync_dir.iterdir():
		yield get_store_app(app_dir.name)


def get_store_app(name) -> StoreApp:
	sync_dir = Path(gconf.get('apps.app_store.sync_dir'))
	app_dir = sync_dir / name
	if not app_dir.exists():
		raise KeyError(f'no app named {name}')
	with get_db() as db:
		is_installed = db.table('apps').contains(where('name') == name)
	with open(app_dir / 'app.json') as f:
		app = json.load(f)
		assert (a := app['name']) == (d := app_dir.name), f'app with name {a} in directory with name {d}'
		return StoreApp(is_installed=is_installed, **app)


def install_store_app(name: str):
	app = get_store_app(name)
	with get_db() as db:
		db.table('apps').insert(AppToInstall(
			**app.dict(),
			installation_reason=InstallationReason.STORE,
		).dict())
		compose.refresh_docker_compose()
	compose.refresh_docker_compose()


def refresh_app_store(ref: str = None):
	log.debug(f'refreshing app store with ref {ref}')
	fs_sync_dir = Path(gconf.get('apps.app_store.sync_dir'))

	apps_project = Gitlab('https://gitlab.com').projects.get(gconf.get('apps.app_store.project_id'))
	archive = tarfile.open(fileobj=io.BytesIO(apps_project.repository_archive(sha=ref or 'master')))

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
