import time
from datetime import datetime
from typing import Optional

from tinydb import Query

from portal_core.database.database import apps_table
from portal_core.model.app_meta import InstalledApp


def test_app_last_access_is_set(api_client):
	assert _get_last_access_time_delta('filebrowser') is None

	response = api_client.get('internal/auth', headers={
		'X-Forwarded-Host': 'filebrowser.myportal.org',
		'X-Forwarded-Uri': '/share/foo'
	})
	response.raise_for_status()

	assert _get_last_access_time_delta('filebrowser') < 0.1
	time.sleep(1)
	assert _get_last_access_time_delta('filebrowser') >= 1

	api_client.get('internal/auth', headers={
		'X-Forwarded-Host': 'filebrowser.myportal.org',
		'X-Forwarded-Uri': '/share/foo'
	})

	assert _get_last_access_time_delta('filebrowser') < 0.1


def test_app_last_access_is_debounced(api_client):
	api_client.get('internal/auth', headers={
		'X-Forwarded-Host': 'filebrowser.myportal.org',
		'X-Forwarded-Uri': '/share/foo'
	})

	assert _get_last_access_time_delta('filebrowser') < 0.1
	last_access = _get_last_access_time('filebrowser')

	time.sleep(0.3)
	api_client.get('internal/auth', headers={
		'X-Forwarded-Host': 'filebrowser.myportal.org',
		'X-Forwarded-Uri': '/share/foo'
	})

	assert _get_last_access_time('filebrowser') == last_access

	time.sleep(0.8)
	api_client.get('internal/auth', headers={
		'X-Forwarded-Host': 'filebrowser.myportal.org',
		'X-Forwarded-Uri': '/share/foo'
	})

	assert _get_last_access_time_delta('filebrowser') < 0.1
	assert _get_last_access_time('filebrowser') != last_access


def _get_last_access_time_delta(app_name: str) -> Optional[float]:
	last_access = _get_last_access_time(app_name)
	if last_access:
		now = datetime.utcnow()
		delta = now - last_access
		return delta.seconds
	else:
		return None


def _get_last_access_time(app_name: str) -> Optional[datetime]:
	with apps_table() as apps:  # type: Table
		app = InstalledApp(**apps.get(Query().name == app_name))
	return app.last_access
