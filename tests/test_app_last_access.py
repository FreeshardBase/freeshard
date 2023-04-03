import time
from datetime import datetime
from typing import Optional

from tinydb import Query

from portal_core.database.database import apps_table
from portal_core.model.app import AppToInstall, InstallationReason, InstalledApp


def test_app_last_access_is_set(api_client):
	insert_app()

	assert _get_last_access_time_delta('foo-app') is None

	api_client.get('internal/auth', headers={
		'X-Forwarded-Host': 'foo-app.myportal.org',
		'X-Forwarded-Uri': '/pub'
	})

	assert _get_last_access_time_delta('foo-app') < 0.1
	time.sleep(1)
	assert _get_last_access_time_delta('foo-app') >= 1

	api_client.get('internal/auth', headers={
		'X-Forwarded-Host': 'foo-app.myportal.org',
		'X-Forwarded-Uri': '/pub'
	})

	assert _get_last_access_time_delta('foo-app') < 0.1


def test_app_last_access_is_debounced(api_client):
	insert_app()

	api_client.get('internal/auth', headers={
		'X-Forwarded-Host': 'foo-app.myportal.org',
		'X-Forwarded-Uri': '/pub'
	})

	assert _get_last_access_time_delta('foo-app') < 0.1
	last_access = _get_last_access_time('foo-app')

	time.sleep(0.3)
	api_client.get('internal/auth', headers={
		'X-Forwarded-Host': 'foo-app.myportal.org',
		'X-Forwarded-Uri': '/pub'
	})

	assert _get_last_access_time('foo-app') == last_access

	time.sleep(0.8)
	api_client.get('internal/auth', headers={
		'X-Forwarded-Host': 'foo-app.myportal.org',
		'X-Forwarded-Uri': '/pub'
	})

	assert _get_last_access_time_delta('foo-app') < 0.1
	assert _get_last_access_time('foo-app') != last_access


def insert_app():
	app = AppToInstall(**{
		'v': '3.1',
		'name': 'foo-app',
		'image': 'foo',
		'version': '1.2.3',
		'port': 1,
		'paths': {
			'': {'access': 'public'},
		},
		'lifecycle': {'idle_time_for_shutdown': 5},
		'reason': InstallationReason.CUSTOM,
	})
	with apps_table() as apps:  # type: Table
		apps.truncate()
		apps.insert(app.dict())


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
