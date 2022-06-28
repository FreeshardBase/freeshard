import gconf
from tinydb import where
from tinydb.table import Table

from portal_core.database.database import apps_table
from portal_core.model.app import InstallationReason, InstalledApp, AppToInstall
from portal_core.service import app_store, app_infra


def refresh_init_apps():
	with apps_table() as apps:  # type: Table
		configured_init_apps = set(gconf.get('apps.initial_apps'))
		installed_init_apps = {InstalledApp(**a).name for a
							   in apps.search(where('installation_reason') == InstallationReason.CONFIG)}

		to_add = configured_init_apps - installed_init_apps
		to_remove = installed_init_apps - configured_init_apps

		for app_name in to_add:
			app = app_store.get_store_app(app_name)
			apps.insert(AppToInstall(
				**app.dict(),
				installation_reason=InstallationReason.CONFIG,
			).dict())

		for app_name in to_remove:
			apps.remove(where('name') == app_name)

	app_infra.refresh_app_infra()
