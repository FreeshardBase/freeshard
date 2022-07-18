from pathlib import Path

import gconf
import psycopg
import yaml
from psycopg.conninfo import make_conninfo

from portal_core.database.database import apps_table
from portal_core.model.app import InstallationReason
from portal_core.service import app_infra, identity


def test_data_dirs_are_created():
	identity.init_default_identity()
	with apps_table() as apps:
		apps.insert({
			'v': '3.1',
			'name': 'foo-app',
			'image': 'foo-app:latest',
			'port': 1,
			'data_dirs': [
				'/user_data/foo',
				'user_data/bar/'
			],
			'paths': {
				'': {
					'access': 'public'
				}
			},
			'reason': InstallationReason.CUSTOM,
		})

	app_infra.refresh_app_infra()

	assert (Path(gconf.get('path_root')) / 'user_data' / 'app_data' / 'foo-app' / 'user_data' / 'foo').is_dir()
	assert (Path(gconf.get('path_root')) / 'user_data' / 'app_data' / 'foo-app' / 'user_data' / 'bar').is_dir()


def test_shared_dirs_are_mounted():
	identity.init_default_identity()
	with apps_table() as apps:
		apps.insert({
			'v': '3.1',
			'name': 'foo-app',
			'image': 'foo-app:latest',
			'port': 1,
			'data_dirs': [
				{
					'path': '/datafoo',
					'shared_dir': 'documents'
				}
			],
			'paths': {
				'': {
					'access': 'public'
				}
			},
			'reason': InstallationReason.CUSTOM,
		})

	app_infra.refresh_app_infra()

	with open(Path(gconf.get('path_root')) / 'core' / 'docker-compose-apps.yml', 'r') as f:
		output = yaml.safe_load(f)
		app = output['services']['foo-app']
		assert '/home/portal/user_data/shared/documents:/datafoo' in app['volumes']


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

	# app database exists
	with psycopg.connect(postgres) as conn:
		with conn.cursor() as cur:
			dbs = cur.execute('SELECT datname FROM pg_database')
			assert ('postgres-app',) in dbs

	# app database is current database when connecting with app's connection string
	app_connection_string = make_conninfo(postgres, user='postgres-app', password='foo')
	with psycopg.connect(app_connection_string) as conn:
		with conn.cursor() as cur:
			dbs = list(cur.execute('SELECT datname FROM pg_database'))
			assert ('postgres-app',) in dbs
			current_db = cur.execute('SELECT current_database()').fetchall()
			assert ('postgres-app',) in current_db

	# postgres values are set as env vars for the app
	with open(Path(gconf.get('path_root')) / 'core' / 'docker-compose-apps.yml', 'r') as f:
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

	with open(Path(gconf.get('path_root')) / 'core' / 'docker-compose-apps.yml', 'r') as f:
		output = yaml.safe_load(f)
		app = output['services']['app-with-docker']
		assert '/var/run/docker.sock:/var/run/docker.sock:ro' in app['volumes']
