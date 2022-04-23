from typing import List

from jinja2 import Template

from portal_core.model import docker_compose as dc
from portal_core.model.app import InstalledApp, Service
from portal_core.model.identity import SafeIdentity


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
	if app.services and Service.DOCKER_SOCK_RO in app.services:
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
