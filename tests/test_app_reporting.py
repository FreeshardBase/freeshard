from datetime import date, timedelta, datetime, time

import responses

from shard_core.database.database import app_usage_track_table
from shard_core.data_model.app_usage import AppUsageTrack, AppUsageReport
from shard_core.service import app_usage_reporting


async def test_app_reporting(app_client, requests_mock: responses.RequestsMock):
    first_day_of_current_month = date.today().replace(day=1)
    first_day_of_last_month = (first_day_of_current_month - timedelta(days=1)).replace(
        day=1
    )
    track_timestamp = datetime.combine(first_day_of_last_month, time(hour=1))

    included_track_1 = AppUsageTrack(
        timestamp=track_timestamp, installed_apps=["foo", "bar"]
    )
    included_track_2 = AppUsageTrack(timestamp=track_timestamp, installed_apps=["foo"])
    excluded_track_early = AppUsageTrack(
        timestamp=datetime.combine(first_day_of_last_month, time(hour=0))
        - timedelta(days=1),
        installed_apps=["early"],
    )
    excluded_track_late = AppUsageTrack(
        timestamp=datetime.combine(first_day_of_current_month, time(hour=0))
        + timedelta(days=1),
        installed_apps=["late"],
    )

    with app_usage_track_table() as tracks:
        tracks.truncate()
        tracks.insert(included_track_1.model_dump())
        tracks.insert(included_track_2.model_dump())
        tracks.insert(excluded_track_early.model_dump())
        tracks.insert(excluded_track_late.model_dump())

    # Call the reporting function directly instead of waiting for the background task
    await app_usage_reporting.report_app_usage()

    # The management API mock captures the POST to /app_usage
    usage_calls = [
        call for call in requests_mock.calls if call.request.path_url == "/app_usage"
    ]
    assert len(usage_calls) >= 1
    report = AppUsageReport.model_validate_json(usage_calls[0].request.body)

    assert report.year == track_timestamp.year
    assert report.month == track_timestamp.month
    assert report.usage["foo"] == 2
    assert report.usage["bar"] == 1
    assert "early" not in report.usage
    assert "late" not in report.usage
