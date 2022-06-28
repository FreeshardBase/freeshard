import gconf

from portal_core import database
from portal_core.database.database import apps_table
from portal_core.model.app import InstallationReason, StoreApp
from portal_core.service import init_apps, app_store, app_infra

init_app_conf = {'apps': {'initial_apps': ['app-foo', 'app-bar']}}


def test_add_init_app(init_db, monkeypatch):
	def mp_get_store_app(name) -> StoreApp:
		return StoreApp(**{
			'name': name,
			'description': f'this is {name}',
			'image': f'image-{name}',
			'port': 1,
			'authentication': {
				'default_access': 'private',
				'peer_paths': None,
				'private_paths': None,
				'public_paths': ['/pub']
			},
			'is_installed': False
		})

	monkeypatch.setattr(app_store, 'get_store_app', mp_get_store_app)
	monkeypatch.setattr(app_infra, 'refresh_app_infra', lambda: None)

	with database.apps_table() as apps:
		for name in ['app-bar', 'app-baz']:
			apps.insert({
				'name': name,
				'description': f'this is {name}',
				'image': f'image-{name}',
				'port': 1,
				'installation_reason': InstallationReason.CONFIG,
			})

		apps.insert({
			'name': 'app-boo',
			'description': 'this is app-boo',
			'image': 'image-app-boo',
			'port': 1,
			'installation_reason': InstallationReason.CUSTOM,
		})

	with gconf.override_conf(init_app_conf):
		init_apps.refresh_init_apps()

	with apps_table() as apps:
		app_names = {a['name'] for a in apps.all()}
	assert app_names == {'app-foo', 'app-bar', 'app-boo'}
