from typing import List, Dict, Set, Union

from portal_core.model import traefik_dyn_config as t
from portal_core.model.app import InstalledApp, EntrypointPort
from portal_core.model.identity import SafeIdentity

HTTP_ENTRYPOINTS = {EntrypointPort.HTTPS_443, EntrypointPort.WSS_9001}
TCP_ENTRYPOINTS = {EntrypointPort.MQTTS_1883}


def traefik_dyn_spec(apps: List[InstalledApp], portal: SafeIdentity) -> t.Model:
	http_routers = {k: v for a in apps for k, v
					in make_routers(a, portal, HTTP_ENTRYPOINTS).items()}
	tcp_routers = {k: v for a in apps for k, v
				   in make_routers(a, portal, TCP_ENTRYPOINTS).items()}
	http_services = {
		f'{a.name}_{ep.entrypoint.value}': make_http_service(f'{ep.entrypoint.value}://{a.name}:{ep.container_port}')
		for a in apps for ep in a.entrypoints if ep.entrypoint in HTTP_ENTRYPOINTS}
	tcp_services = {
		f'{a.name}_{ep.entrypoint.value}': make_tcp_service(f'{ep.entrypoint.value}://{a.name}:{ep.container_port}')
		for a in apps for ep in a.entrypoints if ep.entrypoint in TCP_ENTRYPOINTS}

	model = t.Model()
	model.http = t.Http(
		routers={
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
			**http_routers
		},
		middlewares={
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
		},
		services={
			'portal_core': make_http_service(url='http://portal_core:80/'),
			'web-terminal': make_http_service(url='http://web-terminal:80/'),
			**http_services,
		}
	)
	if tcp_routers and tcp_services:
		model.tcp = t.Tcp(
			routers=tcp_routers,
			services=tcp_services,
		)
	return model


def make_http_service(url: str):
	return t.HttpService(
		__root__=t.HttpServiceItem(
			loadBalancer=t.HttpLoadBalancerService(
				servers=[
					t.Server(url=url)
				]
			)
		)
	)


def make_tcp_service(url: str):
	return t.TcpService(
		__root__=t.TcpServiceItem(
			loadBalancer=t.TcpLoadBalancerService(
				servers=[t.Server1(address=url)]
			)
		)
	)


def make_routers(
		app: InstalledApp,
		portal: SafeIdentity,
		entrypoint_ports: Set[EntrypointPort]
) -> Dict[str, Union[t.HttpRouter, t.TcpRouter]]:
	return {f'{app.name}_{ep.entrypoint.value}': t.HttpRouter(
		rule=f'Host(`{app.name}.{portal.domain}`)',
		entryPoints=[ep.entrypoint],
		service=f'{app.name}_{ep.entrypoint.value}',
		middlewares=['app-error', 'auth'] if ep.entrypoint == EntrypointPort.HTTPS_443 else [],
		tls=make_cert_resolver(portal),
	) for ep in app.entrypoints if ep.entrypoint in entrypoint_ports}


def make_cert_resolver(portal: SafeIdentity):
	return t.Tls1(
		certResolver='letsencrypt',
		domains=[t.Domain(
			main=portal.domain,
			sans=[f'*.{portal.domain}']
		)]
	)
