import asyncio
from datetime import date, timedelta, datetime, time

import pytest
import responses

from portal_core.database.database import app_usage_track_table
from portal_core.model.app_usage import AppUsageTrack, AppUsageReport

pytest_plugins = ('pytest_asyncio',)


@pytest.mark.asyncio
async def test_app_reporting(api_client, requests_mock: responses.RequestsMock):
	first_day_of_current_month = date.today().replace(day=1)
	first_day_of_last_month = (first_day_of_current_month - timedelta(days=1)).replace(day=1)
	track_timestamp = datetime.combine(first_day_of_last_month, time(hour=1))

	included_track_1 = AppUsageTrack(
		timestamp=track_timestamp,
		installed_apps=['foo', 'bar']
	)
	included_track_2 = AppUsageTrack(
		timestamp=track_timestamp,
		installed_apps=['foo']
	)
	excluded_track_early = AppUsageTrack(
		timestamp=datetime.combine(first_day_of_last_month, time(hour=0)) - timedelta(days=1),
		installed_apps=['early'],
	)
	excluded_track_late = AppUsageTrack(
		timestamp=datetime.combine(first_day_of_current_month, time(hour=0)) + timedelta(days=1),
		installed_apps=['late'],
	)

	with app_usage_track_table() as tracks:
		tracks.truncate()
		tracks.insert(included_track_1.dict())
		tracks.insert(included_track_2.dict())
		tracks.insert(excluded_track_early.dict())
		tracks.insert(excluded_track_late.dict())

	await asyncio.sleep(3.5)  # to trigger reporting
	assert len(requests_mock.calls) >= 1
	report = AppUsageReport.parse_raw(requests_mock.calls[0].request.body)

	assert report.year == track_timestamp.year
	assert report.month == track_timestamp.month
	assert report.usage['foo'] == 2
	assert report.usage['bar'] == 1
	assert 'early' not in report.usage
	assert 'late' not in report.usage
