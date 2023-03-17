import gconf

from portal_core.database.database import apps_table
from portal_core.model.app import InstallationReason, InstalledApp, AppToInstall
from portal_core.service import app_store, app_infra


def refresh_init_apps():
	with apps_table() as apps:  # type: Table
		configured_init_apps = set(gconf.get('apps.initial_apps'))
		installed_apps = {InstalledApp(**a).name for a in apps.all()}

		for app_name in configured_init_apps - installed_apps:
			app = app_store.get_store_app(app_name)
			apps.insert(AppToInstall(
				**app.dict(),
				installation_reason=InstallationReason.CONFIG,
			).dict())

	app_infra.refresh_app_infra()
