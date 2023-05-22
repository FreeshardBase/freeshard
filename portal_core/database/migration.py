import logging


from . import database
from ..model.app_meta import InstalledApp, CURRENT_VERSION

log = logging.getLogger(__name__)


def migrate_all():
	with database.apps_table() as apps:
		db_needs_migration = any(_needs_migration(app) for app in apps)
	if not db_needs_migration:
		log.info('database needs no migration')
		return

	with database.apps_table() as apps:  # type: Table
		for app in apps:
			if _needs_migration(app):
				apps.remove(doc_ids=[app.doc_id])
				installed_app = InstalledApp(**app)
				apps.insert(installed_app.dict())
				log.info(f'migrated app {installed_app.name} to app.json format version {CURRENT_VERSION}')
			else:
				log.debug(f'app {installed_app.name} is already at version {CURRENT_VERSION}')


def _needs_migration(app):
	return 'v' not in app or app['v'] != CURRENT_VERSION
