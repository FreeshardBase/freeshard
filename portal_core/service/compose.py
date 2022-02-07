import shutil
from contextlib import suppress
from pathlib import Path

import gconf
import psycopg
from jinja2 import Template
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.errors import DuplicateObject, DuplicateDatabase
from tinydb import Query

from portal_core.database import apps_table, identities_table
from portal_core.model.app import InstalledApp, Service, Postgres
from portal_core.model.identity import Identity


def refresh_docker_compose():
	with apps_table() as apps:
		apps = [InstalledApp(**a) for a in apps.all()]

	for app in apps:
		create_data_dirs(app)
		setup_services(app)

	docker_compose_filename = gconf.get('docker_compose.compose_filename')
	write_docker_compose(apps, docker_compose_filename)


def create_data_dirs(app):
	app_data_dir = Path(gconf.get('apps.app_data_dir')) / app.name
	for data_dir in app.data_dirs or []:
		if isinstance(data_dir, str):
			dir_ = (app_data_dir / str(data_dir).strip('/ '))
			dir_.mkdir(exist_ok=True, parents=True)
		else:
			dir_ = (app_data_dir / str(data_dir.path).strip('/ '))
			dir_.mkdir(exist_ok=True, parents=True)
			shutil.chown(dir_, user=data_dir.uid, group=data_dir.gid)


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
		)


def root_path():
	return Path(__file__).parent.parent


def write_docker_compose(apps, output_path: Path):
	with identities_table() as identities:
		default_identity = Identity(**identities.get(Query().is_default == True))
	portal = {
		'domain': default_identity.domain,
		'id': default_identity.id,
		'public_key_pem': default_identity.public_key_pem,
	}

	template_path = root_path() / 'data' / 'docker-compose.template.yml'
	template = Template(template_path.read_text())
	render_pass_one = template.render(apps=apps, portal=portal)
	render_pass_two = Template(render_pass_one).render(apps={app.name: app for app in apps}, portal=portal)
	with open(output_path, 'w') as f:
		f.write('# == DO NOT MODIFY ==\n# this file is auto-generated\n\n')
		f.write(remove_empty_lines(render_pass_two))


def remove_empty_lines(in_: str):
	lines = in_.split('\n')
	filled_lines = [line for line in lines if line.strip() != '']
	return '\n'.join(filled_lines)
