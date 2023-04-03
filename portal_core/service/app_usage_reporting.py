import logging
from datetime import datetime

from portal_core.database.database import apps_table, app_usage_track_table
from portal_core.model.app import InstalledApp
from portal_core.model.app_usage import AppUsageTrack

log = logging.getLogger(__name__)


async def track_currently_installed_apps():
	with apps_table() as apps:  # type: Table
		all_apps = [InstalledApp.parse_obj(a) for a in apps.all()]
	track = AppUsageTrack(
		timestamp=datetime.utcnow(),
		installed_apps=[app.name for app in all_apps]
	)
	with app_usage_track_table() as tracks:  # type: Table
		tracks.insert(track.dict())
	log.debug(f'created app usage track for {len(track.installed_apps)} apps')
