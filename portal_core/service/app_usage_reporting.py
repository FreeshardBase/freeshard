import asyncio
import logging
from datetime import datetime, date, timedelta
from typing import Dict

import gconf
from pydantic import BaseModel
from requests import HTTPError
from sqlmodel import select
from starlette import status

from portal_core.database.database import session
from portal_core.database.models import AppUsageTrack
from portal_core.model.app_meta import InstalledApp
from portal_core.service.signed_call import signed_request

log = logging.getLogger(__name__)


async def track_currently_installed_apps():
	with session() as session_:
		all_apps = session_.exec(select(InstalledApp)).all()
		for app in all_apps:
			track = AppUsageTrack(
				timestamp=datetime.today(),
				installed_app=app.name
			)
			session_.add(track)
		session_.commit()
		log.debug(f'created app usage track for {len(all_apps)} apps')


class AppUsageReport(BaseModel):
	year: int
	month: int
	usage: Dict[str, float]


async def report_app_usage():
	first_day_of_current_month = date.today().replace(day=1)
	first_day_of_last_month = (first_day_of_current_month - timedelta(days=1)).replace(day=1)

	report = AppUsageReport(year=first_day_of_last_month.year, month=first_day_of_last_month.month, usage={})

	with session() as session_:
		relevant_tracks = session_.exec(select(AppUsageTrack).where(
			AppUsageTrack.timestamp >= first_day_of_last_month,
			AppUsageTrack.timestamp < first_day_of_current_month
		)).all()

		if not relevant_tracks:
			log.warning('no app usage tracks found for reporting')
			return

		for track in relevant_tracks:
			if track.installed_app not in report.usage:
				report.usage[track.installed_app] = 0
			report.usage[track.installed_app] += 1

	api_url = gconf.get('management.api_url')
	url = f'{api_url}/app_usage'

	for i in range(10):
		response = await signed_request('POST', url, json=report.model_dump())
		if response.status_code == status.HTTP_409_CONFLICT:
			log.warning('conflict while sending app usage report, aborting')
			return
		try:
			response.raise_for_status()
		except HTTPError:
			seconds_to_wait = i * 10
			log.info(f'error {response.status_code} while sending app usage report, retrying in {seconds_to_wait}s')
			await asyncio.sleep(seconds_to_wait)
			continue
		else:
			log.info('sent app usage report')
			return
