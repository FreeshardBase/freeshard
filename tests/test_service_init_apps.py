import gconf
import pytest

from portal_core import database
from portal_core.database.database import apps_table
from portal_core.service import init_apps
from portal_core.model.app import InstallationReason

pytestmark = pytest.mark.usefixtures('init_db')

init_app_conf = {'apps': {'initial_apps': {
	'app-foo': {'image': 'image-foo', 'port': 80, 'data_dirs': ['/data', '/config']},
	'app-bar': {'image': 'image-bar', 'port': 80, 'data_dirs': ['/data', '/config']},
}}}


def test_add_init_app(init_db):
	with database.apps_table() as apps:
		for name in ['app-bar', 'app-baz']:
			apps.insert({
				'name': name,
				'description': f'this is {name}',
				'image': f'image-{name}',
				'port': 1,
				'installation_reason': InstallationReason.CONFIG,
				'authentication': {
					'default_access': 'private',
					'peer_paths': None,
					'private_paths': None,
					'public_paths': ['/pub']
				}
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
