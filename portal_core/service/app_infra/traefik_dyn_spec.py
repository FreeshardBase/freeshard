from typing import List

from portal_core.model import traefik_dyn_config as t
from portal_core.model.app import InstalledApp, EntrypointPort, Entrypoint
from portal_core.model.identity import SafeIdentity

HTTP_ENTRYPOINTS = {EntrypointPort.HTTPS_443, EntrypointPort.WSS_9001}
TCP_ENTRYPOINTS = {EntrypointPort.MQTTS_1883}


def traefik_dyn_spec(apps: List[InstalledApp], portal: SafeIdentity) -> t.Model:
	model = t.Model()
	_add_http_section(model, portal)
	_add_tcp_section(model, portal)
	for a in apps:
		for ep in a.entrypoints:
			_add_router(model, ep, a, portal)
			_add_service(model, ep, a)

	# this is needed because traefik cannot handle empty yaml objects here
	if not model.tcp.routers:
		del model.tcp.routers
	if not model.tcp.services:
		del model.tcp.services
	if not model.tcp.dict():
		del model.tcp

	return model


def _add_http_section(model: t.Model, portal: SafeIdentity):
	_routers = {
		'portal_core_public': t.HttpRouter(
			rule='PathPrefix(`/core/public`)',
			entryPoints=['https'],
			service='portal_core',
			middlewares=['strip', 'auth-public'],
			tls=make_cert_resolver(portal),
		),
		'portal_core_private': t.HttpRouter(
			rule='PathPrefix(`/core/protected`)',
			entryPoints=['https'],
			service='portal_core',
			middlewares=['strip', 'auth-private'],
			tls=make_cert_resolver(portal),
		),
		'web-terminal': t.HttpRouter(
			rule='PathPrefix(`/`)',
			priority=1,
			entryPoints=['https'],
			service='web-terminal',
			tls=make_cert_resolver(portal),
		),
		'traefik': t.HttpRouter(
			rule=f'HostRegexp(`traefik.{portal.domain}`)',
			entryPoints=['https'],
			service='api@internal',
			middlewares=['auth-private'],
			tls=make_cert_resolver(portal),
		),
	}

	_middlewares = {
		'strip': t.HttpMiddleware(
			__root__=t.HttpMiddlewareItem21(
				stripPrefix=t.StripPrefixMiddleware(
					prefixes=['/core/']
				)
			)
		),
		'auth-private': t.HttpMiddleware(
			__root__=t.HttpMiddlewareItem9(
				forwardAuth=t.ForwardAuthMiddleware(
					address='http://portal_core/internal/authenticate_terminal',
					authResponseHeaders=[
						'X-Ptl-Client-Type',
						'X-Ptl-Client-Id',
						'X-Ptl-Client-Name',
					],
				)
			)
		),
		'auth-public': t.HttpMiddleware(
			__root__=t.HttpMiddlewareItem10(
				headers=t.HeadersMiddleware(
					customRequestHeaders={
						'X-Ptl-Client-Type': 'public',
						'X-Ptl-Client-Id': '',
						'X-Ptl-Client-Name': '',
					}
				)
			)
		),
		'auth': t.HttpMiddleware(
			__root__=t.HttpMiddlewareItem9(
				forwardAuth=t.ForwardAuthMiddleware(
					address='http://portal_core/internal/auth',
					authResponseHeadersRegex='^X-Ptl-.*'
				)
			)
		),
		'app-error': t.HttpMiddleware(
			__root__=t.HttpMiddlewareItem8(
				errors=t.ErrorsMiddleware(
					status=['500-599', '400-499'],
					service='portal_core',
					query='/internal/app_error/{status}'
				)
			)
		)
	}
	_services = {
		'portal_core': t.HttpService(
			__root__=t.HttpServiceItem(
				loadBalancer=t.HttpLoadBalancerService(
					servers=[
						t.Server(url='http://portal_core:80/')
					]
				)
			)
		),
		'web-terminal': t.HttpService(
			__root__=t.HttpServiceItem(
				loadBalancer=t.HttpLoadBalancerService(
					servers=[
						t.Server(url='http://web-terminal:80/')
					]
				)
			)
		),
	}
	model.http = t.Http(
		routers=_routers,
		middlewares=_middlewares,
		services=_services
	)


def _add_tcp_section(model: t.Model, portal: SafeIdentity):
	model.tcp = t.Tcp(
		routers={},
		services={},
	)


def _add_router(model: t.Model, entrypoint: Entrypoint, app: InstalledApp, portal: SafeIdentity):
	ep_value = entrypoint.entrypoint_port.value
	if entrypoint.entrypoint_port == EntrypointPort.HTTPS_443:
		model.http.routers[f'{app.name}_{ep_value}'] = t.HttpRouter(
			rule=f'Host(`{app.name}.{portal.domain}`)',
			entryPoints=[ep_value],
			service=f'{app.name}_{ep_value}',
			middlewares=['app-error', 'auth'] if entrypoint == EntrypointPort.HTTPS_443 else [],
			tls=make_cert_resolver(portal),
		)
	elif entrypoint.entrypoint_port == EntrypointPort.WSS_9001:
		model.http.routers[f'{app.name}_{ep_value}'] = t.HttpRouter(
			rule=f'Host(`{app.name}.{portal.domain}`)',
			entryPoints=[ep_value],
			service=f'{app.name}_{ep_value}',
			tls=make_cert_resolver(portal),
		)
	elif entrypoint.entrypoint_port == EntrypointPort.MQTTS_1883:
		model.tcp.routers[f'{app.name}_{ep_value}'] = t.TcpRouter(
			rule=f'Host(`{app.name}.{portal.domain}`)',
			entryPoints=[ep_value],
			service=f'{app.name}_{ep_value}',
			tls=make_cert_resolver(portal),
		)
	else:
		raise ValueError('Invalid entrypoint')


def _add_service(model: t.Model, entrypoint: Entrypoint, app: InstalledApp):
	ep_value = entrypoint.entrypoint_port.value
	if entrypoint.entrypoint_port == EntrypointPort.HTTPS_443:
		model.http.services[f'{app.name}_{ep_value}'] = t.HttpService(
			__root__=t.HttpServiceItem(
				loadBalancer=t.HttpLoadBalancerService(
					servers=[
						t.Server(url=f'http://{app.name}:{entrypoint.container_port}')
					]
				)
			)
		)
	elif entrypoint.entrypoint_port == EntrypointPort.WSS_9001:
		model.http.services[f'{app.name}_{ep_value}'] = t.HttpService(
			__root__=t.HttpServiceItem(
				loadBalancer=t.HttpLoadBalancerService(
					servers=[
						t.Server(url=f'ws://{app.name}:{entrypoint.container_port}')
					]
				)
			)
		)
	elif entrypoint.entrypoint_port == EntrypointPort.MQTTS_1883:
		model.tcp.services[f'{app.name}_{ep_value}'] = t.TcpService(
			__root__=t.TcpServiceItem(
				loadBalancer=t.TcpLoadBalancerService(
					servers=[
						t.Server1(address=f'mqtt://{app.name}:{entrypoint.container_port}')
					]
				)
			)
		)
	else:
		raise ValueError('Invalid entrypoint')


def make_cert_resolver(portal: SafeIdentity):
	return t.Tls1(
		certResolver='letsencrypt',
		domains=[t.Domain(
			main=portal.domain,
			sans=[f'*.{portal.domain}']
		)]
	)
