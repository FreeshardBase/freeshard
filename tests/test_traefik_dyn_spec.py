from pathlib import Path

import gconf
import yaml

from tests.conftest import requires_test_env


@requires_test_env('full')
async def test_template_is_written(api_client):
	with open(Path(gconf.get('path_root')) / 'core' / 'traefik_dyn' / 'traefik_dyn.yml', 'r') as f:
		output = yaml.safe_load(f)
		out_middlewares: dict = output['http']['middlewares']

		assert set(out_middlewares.keys()) == {
			'app-error', 'auth', 'strip', 'auth-public', 'auth-private', 'auth-management'}
		assert 'authResponseHeadersRegex' in out_middlewares['auth']['forwardAuth']

		out_services_http: dict = output['http']['services']
		assert set(out_services_http.keys()) == {'shard_core', 'web-terminal', 'filebrowser_http'}
		assert out_services_http['filebrowser_http']['loadBalancer']['servers'] == [{'url': 'http://filebrowser:80'}]

		out_routers_http: dict = output['http']['routers']
		assert set(out_routers_http.keys()) == {
			'shard_core_private', 'shard_core_public', 'shard_core_management', 'web-terminal', 'traefik',
			'filebrowser_http'}
		assert out_routers_http['filebrowser_http']['service'] == 'filebrowser_http'
