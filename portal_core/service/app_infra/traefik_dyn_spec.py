from typing import List, Dict

from portal_core.model import traefik_dyn_config as t
from portal_core.model.app import InstalledApp, EntrypointPort
from portal_core.model.identity import SafeIdentity


def traefik_dyn_spec(apps: List[InstalledApp], portal: SafeIdentity) -> t.Model:
	app_routers = {k: v for a in apps for k, v in make_app_routers(a, portal).items()}
	return t.Model(
		http=t.Http(
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
				**app_routers
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
				'portal_core': make_service(url='http://portal_core:80/'),
				'web-terminal': make_service(url='http://web-terminal:80/'),
				**{f'{a.name}_{ep.entrypoint.value}': make_service(f'http://{a.name}:{ep.container_port}')
				   for a in apps for ep in a.entrypoints}
			}
		)
	)


def make_service(url: str):
	return t.HttpService(
		__root__=t.HttpServiceItem(
			loadBalancer=t.HttpLoadBalancerService(
				servers=[
					t.Server(url=url)
				]
			)
		)
	)


def make_app_routers(app: InstalledApp, portal: SafeIdentity) -> Dict[str, t.HttpRouter]:
	return {f'{app.name}_{ep.entrypoint.value}': t.HttpRouter(
		rule=f'Host(`{app.name}.{portal.domain}`)',
		entryPoints=[ep.entrypoint],
		service=f'{app.name}_{ep.entrypoint.value}',
		middlewares=['app-error', 'auth'] if ep.entrypoint == EntrypointPort.HTTPS_443 else [],
		tls=make_cert_resolver(portal),
	) for ep in app.entrypoints}


def make_cert_resolver(portal: SafeIdentity):
	return t.Tls1(
		certResolver='letsencrypt',
		domains=[t.Domain(
			main=portal.domain,
			sans=[f'*.{portal.domain}']
		)]
	)
