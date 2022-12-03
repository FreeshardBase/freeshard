import shutil
from contextlib import suppress
from pathlib import Path

import gconf
import psycopg
import pydantic
import yaml
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.errors import DuplicateObject, DuplicateDatabase
from tinydb import Query

from portal_core.database.database import apps_table, identities_table
from portal_core.model.app import InstalledApp, Service, Postgres
from portal_core.model.identity import Identity, SafeIdentity
from .docker_compose_spec import compose_spec
from .traefik_dyn_spec import traefik_dyn_spec


def refresh_app_infra():
	with apps_table() as apps:
		apps = [InstalledApp(**a) for a in apps.all()]

	for app in apps:
		create_data_dirs(app)
		setup_services(app)

	with identities_table() as identities:
		default_identity = Identity(**identities.get(Query().is_default == True))
	portal = SafeIdentity(**default_identity.dict())

	docker_compose_filename = Path(gconf.get('path_root')) / 'core' / 'docker-compose-apps.yml'
	write_to_yaml(compose_spec(apps, portal), docker_compose_filename)

	traefik_dyn_filename = Path(gconf.get('path_root')) / 'core' / 'traefik_dyn' / 'traefik_dyn.yml'
	write_to_yaml(traefik_dyn_spec(apps, portal), traefik_dyn_filename)
	# todo: start apps that should be always on


def create_data_dirs(app):
	app_data_dir = Path(gconf.get('path_root')) / 'user_data' / 'app_data' / app.name
	for data_dir in app.data_dirs or []:
		if isinstance(data_dir, str):
			dir_ = (app_data_dir / str(data_dir).strip('/ '))
			dir_.mkdir(exist_ok=True, parents=True)
		elif not data_dir.shared_dir:
			dir_ = (app_data_dir / str(data_dir.path).strip('/ '))
			dir_.mkdir(exist_ok=True, parents=True)
			shutil.chown(dir_, user=data_dir.uid or None, group=data_dir.gid or None)


def setup_services(app: InstalledApp):
	if app.services and Service.POSTGRES in app.services:
		pg_host = gconf.get('services.postgres.host')
		pg_port = gconf.get('services.postgres.port')
		pg_user = gconf.get('services.postgres.user')
		pg_password = gconf.get('services.postgres.password')
		password = 'foo'
		connection_string = make_conninfo('', host=pg_host, port=pg_port, user=pg_user, password=pg_password)
		with psycopg.connect(connection_string) as conn:
			with conn.cursor() as cur:
				with suppress(DuplicateObject):
					cur.execute(sql.SQL('''
						CREATE USER {}
						WITH PASSWORD {}
					''').format(
						sql.Identifier(app.name),
						sql.Literal(password)
					))
		with psycopg.connect(connection_string, autocommit=True) as conn:
			with conn.cursor() as cur:
				with suppress(DuplicateDatabase):
					cur.execute(sql.SQL('''
						CREATE DATABASE {}
						WITH OWNER {}
					''').format(
						sql.Identifier(app.name),
						sql.Identifier(app.name)
					))
		app.postgres = Postgres(
			connection_string=f'postgres://{app.name}:{password}@{pg_host}:{pg_port}/{app.name}',
			userspec=f'{app.name}:{password}',
			user=app.name,
			password=password,
			hostspec=f'{pg_host}:{pg_port}',
			host=pg_host,
			port=pg_port,
			database=app.name,
		)


def write_to_yaml(spec: pydantic.BaseModel, output_path: Path):
	output_path.parent.mkdir(exist_ok=True, parents=True)
	with open(output_path, 'w') as f:
		f.write('# == DO NOT MODIFY ==\n# this file is auto-generated\n\n')
		f.write(yaml.dump(spec.dict(exclude_none=True)))
