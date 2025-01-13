import asyncio
from datetime import date, timedelta, datetime, time

import responses

from portal_core.database.database import session
from portal_core.database.models import AppUsageTrack
from portal_core.service.app_usage_reporting import AppUsageReport
from tests.conftest import requires_test_env


@requires_test_env('full')
async def test_app_reporting(api_client, requests_mock: responses.RequestsMock):
	first_day_of_current_month = date.today().replace(day=1)
	first_day_of_last_month = (first_day_of_current_month - timedelta(days=1)).replace(day=1)
	track_timestamp = datetime.combine(first_day_of_last_month, time(hour=1))

	included_track_1 = AppUsageTrack(
		timestamp=track_timestamp,
		installed_app='foo'
	)
	included_track_2 = AppUsageTrack(
		timestamp=track_timestamp,
		installed_app='bar'
	)
	included_track_3 = AppUsageTrack(
		timestamp=track_timestamp + timedelta(days=1),
		installed_app='foo'
	)
	excluded_track_early = AppUsageTrack(
		timestamp=datetime.combine(first_day_of_last_month, time(hour=0)) - timedelta(days=1),
		installed_app='early'
	)
	excluded_track_late = AppUsageTrack(
		timestamp=datetime.combine(first_day_of_current_month, time(hour=0)) + timedelta(days=1),
		installed_app='late'
	)

	with session() as session_:
		session_.add(included_track_1)
		session_.add(included_track_2)
		session_.add(included_track_3)
		session_.add(excluded_track_early)
		session_.add(excluded_track_late)
		session_.commit()

	await asyncio.sleep(3.5)  # to trigger reporting
	assert len(requests_mock.calls) >= 1
	report = AppUsageReport.model_validate_json(requests_mock.calls[0].request.body)

	assert report.year == track_timestamp.year
	assert report.month == track_timestamp.month
	assert report.usage['foo'] == 2
	assert report.usage['bar'] == 1
	assert 'early' not in report.usage
	assert 'late' not in report.usage
