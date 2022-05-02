from typing import List

from portal_core.model import traefik_dyn_config as t
from portal_core.model.app import InstalledApp
from portal_core.model.identity import SafeIdentity


def traefik_dyn_spec(apps: List[InstalledApp], portal: SafeIdentity) -> t.Model:
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
				**{a.name: make_app_router(a, portal) for a in apps}
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
				**{a.name: make_service(f'http://{a.name}:{a.port}') for a in apps}
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


def make_app_router(app: InstalledApp, portal: SafeIdentity) -> t.HttpRouter:
	return t.HttpRouter(
		rule=f'Host(`{app.name}.{portal.domain}`)',
		entryPoints=['https'],
		service=app.name,
		middlewares=['app-error', 'auth'],
		tls=make_cert_resolver(portal),
	)


def make_cert_resolver(portal: SafeIdentity):
	return t.Tls1(
		certResolver='letsencrypt',
		domains=[t.Domain(
			main=portal.domain,
			sans=[f'*.{portal.domain}']
		)]
	)
