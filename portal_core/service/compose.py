import shutil
from contextlib import suppress
from pathlib import Path
from typing import List

import gconf
import psycopg
import yaml
from jinja2 import Template
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.errors import DuplicateObject, DuplicateDatabase
from tinydb import Query

from portal_core.database.database import apps_table, identities_table
from portal_core.model.app import InstalledApp, Service, Postgres
from portal_core.model.identity import Identity, SafeIdentity

import portal_core.model.docker_compose as dc


def refresh_docker_compose():
	with apps_table() as apps:
		apps = [InstalledApp(**a) for a in apps.all()]

	for app in apps:
		create_data_dirs(app)
		setup_services(app)

	with identities_table() as identities:
		default_identity = Identity(**identities.get(Query().is_default == True))
	portal = SafeIdentity.from_identity(default_identity)

	spec = compose_spec(apps, portal)
	docker_compose_filename = gconf.get('docker_compose.compose_filename')
	write_docker_compose(spec, docker_compose_filename)


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
			database=app.name,
		)


def write_docker_compose(spec: dc.ComposeSpecification, output_path: Path):
	with open(output_path, 'w') as f:
		f.write('# == DO NOT MODIFY ==\n# this file is auto-generated\n\n')
		f.write(yaml.dump(spec.dict(exclude_none=True)))


def compose_spec(apps: List[InstalledApp], portal: SafeIdentity) -> dc.ComposeSpecification:
	return dc.ComposeSpecification(
		version='3.5',
		networks={
			'portal': dc.Network(name='portal')
		},
		services={app.name: service_spec(app, portal) for app in apps}
	)


def service_spec(app: InstalledApp, portal: SafeIdentity):
	return dc.Service(
		image=app.image,
		container_name=app.name,
		restart='always',
		networks=dc.ListOfStrings.parse_obj(['portal']),
		volumes=volumes(app),
		environment=dc.ListOrDict.parse_obj(environment(app, portal)),
		labels=dc.ListOrDict.parse_obj(traefik_labels(app, portal))
	)


def volumes(app: InstalledApp) -> List[str]:
	result = []
	for data_dir in app.data_dirs or []:
		if isinstance(data_dir, str):
			result.append(f'/home/portal/user_data/app_data/{app.name}/{data_dir}:{data_dir}')
		else:
			result.append(f'/home/portal/user_data/app_data/{app.name}/{data_dir.path}:{data_dir.path}')
	if Service.DOCKER_SOCK_RO in app.services:
		result.append('/var/run/docker.sock:/var/run/docker.sock:ro')
	return result


def environment(app: InstalledApp, portal: SafeIdentity) -> List[str]:
	if app.env_vars:
		def render(v):
			return Template(v).render(portal=portal, postgres=app.postgres or None)

		return [f'{k}={render(v)}' for k, v in app.env_vars.items()]
	else:
		return []


def traefik_labels(app: InstalledApp, portal: SafeIdentity) -> List[str]:
	return [
		'traefik.enable=true',
		f'traefik.http.services.{app.name}.loadbalancer.server.port={app.port}',
		f'traefik.http.routers.{app.name}_router.entrypoints=https',
		f'traefik.http.routers.{app.name}_router.rule=Host(`{app.name}.{portal.domain}`)',
		f'traefik.http.routers.{app.name}_router.tls=true',
		f'traefik.http.routers.{app.name}_router.tls.certresolver=letsencrypt',
		f'traefik.http.routers.{app.name}_router.tls.domains[0].main={portal.domain}',
		f'traefik.http.routers.{app.name}_router.tls.domains[0].sans=*.{portal.domain}',
		f'traefik.http.routers.{app.name}_router.middlewares=auth@file',
		f'traefik.http.routers.{app.name}_router.service={app.name}'
	]
