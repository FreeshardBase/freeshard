import asyncio
import logging
from datetime import datetime, date, timedelta

import gconf
from requests import HTTPError
from starlette import status

from shard_core.database.connection import db_conn
from shard_core.database import installed_apps as installed_apps_db
from shard_core.database import app_usage as app_usage_db
from shard_core.data_model.app_meta import InstalledApp
from shard_core.data_model.app_usage import AppUsageTrack, AppUsageReport
from shard_core.service.signed_call import signed_request

log = logging.getLogger(__name__)


async def track_currently_installed_apps():
    async with db_conn() as conn:
        all_apps_rows = await installed_apps_db.get_all(conn)
    all_apps = [InstalledApp.parse_obj(a) for a in all_apps_rows]
    track = AppUsageTrack(
        timestamp=datetime.utcnow(), installed_apps=[app.name for app in all_apps]
    )
    async with db_conn() as conn:
        await app_usage_db.insert(conn, track.dict())
    log.debug(f"created app usage track for {len(track.installed_apps)} apps")


async def report_app_usage():
    first_day_of_current_month = date.today().replace(day=1)
    first_day_of_last_month = (first_day_of_current_month - timedelta(days=1)).replace(
        day=1
    )
    start = datetime.combine(first_day_of_last_month, datetime.min.time())
    end = datetime.combine(first_day_of_current_month, datetime.min.time())

    report = AppUsageReport(year=start.year, month=start.month, usage={})

    async with db_conn() as conn:
        relevant_tracks = await app_usage_db.search_by_time_range(conn, start, end)

    if not relevant_tracks:
        log.warning("no app usage tracks found for reporting")
        return

    for t in relevant_tracks:
        for app in AppUsageTrack.parse_obj(t).installed_apps:
            if app not in report.usage:
                report.usage[app] = 0
            report.usage[app] += 1

    api_url = gconf.get("management.api_url")
    url = f"{api_url}/app_usage"

    for i in range(10):
        response = await signed_request("POST", url, json=report.dict())
        if response.status_code == status.HTTP_409_CONFLICT:
            log.warning("conflict while sending app usage report, aborting")
            return
        try:
            response.raise_for_status()
        except HTTPError:
            seconds_to_wait = i * 10
            log.info(
                f"error {response.status_code} while sending app usage report, retrying in {seconds_to_wait}s"
            )
            await asyncio.sleep(seconds_to_wait)
            continue
        else:
            log.info("sent app usage report")
            return
