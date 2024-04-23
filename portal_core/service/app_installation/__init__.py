import logging

import gconf

from portal_core.database.database import installed_apps_table
from portal_core.model.app_meta import InstallationReason, InstalledApp, Status
from portal_core.util import signals
from portal_core.util.subprocess import subprocess
from .exceptions import AppAlreadyInstalled, AppDoesNotExist
from .util import update_app_status, app_exists_in_store, app_exists_in_db
from .worker import installation_worker, InstallationTask

log = logging.getLogger(__name__)


async def install_app_from_store(
		name: str,
		installation_reason: InstallationReason = InstallationReason.STORE,
):
	if not await app_exists_in_store(name):
		raise AppDoesNotExist(name)

	if app_exists_in_db(name):
		raise AppAlreadyInstalled(name)

	with installed_apps_table() as installed_apps:
		installed_app = InstalledApp(
			name=name,
			installation_reason=installation_reason,
			status=Status.INSTALLATION_QUEUED,
		)
		installed_apps.insert(installed_app.dict())

	installation_task = InstallationTask(
		app_name=name,
		task_type='install from store',
	)
	installation_worker.enqueue(installation_task)
	signals.async_on_apps_update.send()
	log.info(f'created {installation_task}')


async def install_app_from_existing_zip(
		name: str,
		installation_reason: InstallationReason = InstallationReason.CUSTOM
):
	if not await app_exists_in_store(name):
		raise AppDoesNotExist(name)

	if app_exists_in_db(name):
		raise AppAlreadyInstalled(name)

	with installed_apps_table() as installed_apps:
		installed_app = InstalledApp(
			name=name,
			installation_reason=installation_reason,
			status=Status.INSTALLATION_QUEUED,
		)
		installed_apps.insert(installed_app.dict())

	installation_task = InstallationTask(
		app_name=name,
		task_type='install from zip',
	)
	installation_worker.enqueue(installation_task)
	signals.async_on_apps_update.send()
	log.info(f'created {installation_task}')


def uninstall_app(name: str):
	try:
		update_app_status(name, Status.UNINSTALLATION_QUEUED)
	except KeyError:
		log.warning(f'during queueing of uninstallation of {name}: app not found in database')

	uninstallation_task = InstallationTask(
		app_name=name,
		task_type='uninstall',
	)
	installation_worker.enqueue(uninstallation_task)

	signals.async_on_apps_update.send()
	log.info(f'created {uninstallation_task}')


async def reinstall_app(name: str):
	if not await app_exists_in_store(name):
		raise AppDoesNotExist(name)
	update_app_status(name, Status.UNINSTALLATION_QUEUED)

	uninstallation_task = InstallationTask(
		app_name=name,
		task_type='uninstall',
	)
	installation_worker.enqueue(uninstallation_task)

	installation_task = InstallationTask(
		app_name=name,
		task_type='install from store',
	)
	installation_worker.enqueue(installation_task)

	log.info(f'created {uninstallation_task}')
	log.info(f'created {installation_task}')


async def refresh_init_apps():
	configured_init_apps = set(gconf.get('apps.initial_apps'))
	with installed_apps_table() as apps:
		installed_apps = {app['name'] for app in apps.all()}

	for app_name in configured_init_apps - installed_apps:
		log.info(f'installing initial app {app_name}')
		await install_app_from_store(app_name, InstallationReason.CONFIG)
	log.debug('refreshed initial apps')


async def login_docker_registries():
	registries = gconf.get('apps.registries')
	for r in registries:
		await subprocess('docker', 'login', '-u', r['username'], '-p', r['password'], r['uri'])
		log.debug(f'logged in to registry {r["uri"]}')
