from pathlib import Path

import gconf
import psycopg
import pytest
import yaml
from psycopg.conninfo import make_conninfo

from portal_core.database.database import apps_table
from portal_core.model.app import InstallationReason
from portal_core.service import app_infra, identity

pytestmark = pytest.mark.usefixtures('tempfile_path_config')


def test_data_dirs_are_created():
	identity.init_default_identity()
	with apps_table() as apps:
		apps.insert({
			'name': 'foo-app',
			'image': 'foo-app:latest',
			'version': '1.2.3',
			'port': 1,
			'data_dirs': [
				'/user_data/foo',
				'user_data/bar/'
			],
			'authentication': {
				'default_access': 'public',
			},
			'reason': InstallationReason.CUSTOM,
		})

	app_infra.refresh_app_infra()

	assert (Path(gconf.get('apps.app_data_dir')) / 'foo-app' / 'user_data' / 'foo').is_dir()
	assert (Path(gconf.get('apps.app_data_dir')) / 'foo-app' / 'user_data' / 'bar').is_dir()


def test_postgres_is_setup(postgres):
	identity.init_default_identity()
	with apps_table() as apps:
		apps.insert({
			'name': 'postgres-app',
			'image': 'postgres-app:latest',
			'version': '1.2.3',
			'port': 2,
			'services': ['postgres'],
			'env_vars': {
				'pg_user': '{{postgres.user}}',
				'pg_password': '{{postgres.password}}'
			},
			'reason': InstallationReason.CUSTOM,
		})

	app_infra.refresh_app_infra()

	pg_host = gconf.get('services.postgres.host')
	pg_port = gconf.get('services.postgres.port')
	pg_user = gconf.get('services.postgres.user')
	pg_password = gconf.get('services.postgres.password')

	admin_connection_string = make_conninfo('', host=pg_host, port=pg_port, user=pg_user, password=pg_password)
	with psycopg.connect(admin_connection_string) as conn:
		with conn.cursor() as cur:
			dbs = cur.execute('SELECT datname FROM pg_database')
			assert ('postgres-app',) in dbs

	app_connection_string = make_conninfo(admin_connection_string, user='postgres-app', password='foo')
	with psycopg.connect(app_connection_string) as conn:
		with conn.cursor() as cur:
			dbs = list(cur.execute('SELECT datname FROM pg_database'))
			print(dbs)
			assert ('postgres-app',) in dbs
			current_db = cur.execute('SELECT current_database()').fetchall()
			assert ('postgres-app',) in current_db

	with open(gconf.get('app_infra.compose_filename'), 'r') as f:
		output = yaml.safe_load(f)
		postgres_app = output['services']['postgres-app']
		assert 'pg_user=postgres-app' in postgres_app['environment']
		assert 'pg_password=foo' in postgres_app['environment']


def test_docker_socket_is_mounted():
	identity.init_default_identity()
	with apps_table() as apps:
		apps.insert({
			'name': 'app-with-docker',
			'image': 'app-with-docker:latest',
			'version': '1.2.3',
			'port': 2,
			'reason': InstallationReason.CUSTOM,
			'services': ['docker_sock_ro']
		})

	app_infra.refresh_app_infra()

	with open(gconf.get('app_infra.compose_filename'), 'r') as f:
		output = yaml.safe_load(f)
		app = output['services']['app-with-docker']
		assert '/var/run/docker.sock:/var/run/docker.sock:ro' in app['volumes']
