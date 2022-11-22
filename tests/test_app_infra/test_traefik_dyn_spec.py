from pathlib import Path

import gconf
import yaml

from portal_core.database.database import apps_table
from portal_core.model.app import InstallationReason
from portal_core.service import identity, app_infra


def test_template_is_written():
	identity.init_default_identity()
	with apps_table() as apps:
		apps.insert({
			'v': '4.0',
			'name': 'baz-app',
			'image': 'baz-app:latest',
			'version': '1.2.3',
			'paths': {'': {'access': 'public'}},
			'entrypoints': [
				{'container_port': 2, 'entrypoint': 'https'},
				{'container_port': 3, 'entrypoint': 'mqtt'},
			],
			'env_vars': {
				'baz-env': 'foo',
				'url': 'https://{{ portal.domain }}/baz'
			},
			'reason': InstallationReason.CUSTOM,
		})

	app_infra.refresh_app_infra()

	with open(Path(gconf.get('path_root')) / 'core' / 'traefik_dyn' / 'traefik_dyn.yml', 'r') as f:
		output = yaml.safe_load(f)
		out_middlewares: dict = output['http']['middlewares']

		assert set(out_middlewares.keys()) == {'app-error', 'auth', 'strip', 'auth-public', 'auth-private'}
		assert 'authResponseHeadersRegex' in out_middlewares['auth']['forwardAuth']

		out_services: dict = output['http']['services']
		assert set(out_services.keys()) == {'portal_core', 'web-terminal', 'baz-app_https', 'baz-app_mqtt'}
		assert out_services['baz-app_https']['loadBalancer']['servers'] == [{'url': 'http://baz-app:2'}]

		out_routers: dict = output['http']['routers']
		assert set(out_routers.keys()) == {
			'portal_core_private', 'portal_core_public', 'web-terminal', 'traefik', 'baz-app_https', 'baz-app_mqtt'}
		assert out_routers['baz-app_https']['service'] == 'baz-app_https'
