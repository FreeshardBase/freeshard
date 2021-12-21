import gconf
import pytest

from portal_core import service, database, model

pytestmark = pytest.mark.usefixtures('init_db')

init_app_conf = {'apps': {'initial_apps': {
	'app-foo': {'image': 'image-foo', 'port': 80, 'data_dirs': ['/data', '/config']},
	'app-bar': {'image': 'image-bar', 'port': 80, 'data_dirs': ['/data', '/config']},
}}}


def test_add_init_app(init_db):
	with database.get_db() as db:
		for name in ['app-bar', 'app-baz']:
			db.table('apps').insert({
				'name': name,
				'description': f'this is {name}',
				'image': f'image-{name}',
				'port': 1,
				'installation_reason': model.InstallationReason.CONFIG,
			})

		db.table('apps').insert({
			'name': 'app-boo',
			'description': 'this is app-boo',
			'image': 'image-app-boo',
			'port': 1,
			'installation_reason': model.InstallationReason.CUSTOM,
		})

	with gconf.override_conf(init_app_conf):
		service.refresh_init_apps()

	with database.get_db() as db:
		app_names = {a['name'] for a in db.table('apps').all()}
	assert app_names == {'app-foo', 'app-bar', 'app-boo'}
