import gconf
from tinydb import where

from portal_core.database import get_db
from portal_core.model import InstallationReason, InstalledApp, AppToInstall


def refresh_init_apps():
	configured_init_apps = gconf.get('apps.initial_apps')
	with get_db() as db:
		installed_init_apps = [InstalledApp(**a) for a
			in db.table('apps').search(where('installation_reason') == InstallationReason.CONFIG)]

	to_add = set(configured_init_apps.keys()) - {a.name for a in installed_init_apps}
	to_remove = {a.name for a in installed_init_apps} - set(configured_init_apps.keys())

	with get_db() as db:
		table = db.table('apps')
		for app_name in to_add:
			app = AppToInstall(
				name=app_name,
				**gconf.get('apps.initial_apps', app_name),
				installation_reason=InstallationReason.CONFIG,
			)
			table.insert(app.dict())

		for app_name in to_remove:
			table.remove(where('name') == app_name)
