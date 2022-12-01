import re
from pathlib import Path

import gconf
import yaml

from portal_core.database.database import apps_table
from portal_core.model.app import InstallationReason
from portal_core.service import identity, app_infra


def test_template_is_written():
	i = identity.init_default_identity()
	with apps_table() as apps:
		apps.insert({
			'v': '4.0',
			'name': 'baz-app',
			'image': 'baz-app:latest',
			'entrypoints': [
				{'container_port': 2, 'entrypoint_port': 'http'},
				{'container_port': 3, 'entrypoint_port': 'mqtt'},
			],
			'paths': {
				'': {'access': 'private'},
			},
			'env_vars': {
				'baz-env': 'foo',
				'url': 'https://{{ portal.domain }}/baz',
				'short_id': '{{ portal.short_id }}'
			},
			'reason': InstallationReason.CUSTOM,
		})

	app_infra.refresh_app_infra()

	with open(Path(gconf.get('path_root')) / 'core' / 'docker-compose-apps.yml', 'r') as f:
		output = yaml.safe_load(f)
		baz_app = output['services']['baz-app']
		assert 'baz-env=foo' in baz_app['environment']
		assert f'short_id={i.short_id}' in baz_app['environment']
		assert any(re.search('url=https://.*\.p\.getportal\.org/baz', e) for e in baz_app['environment'])
		assert '2:2' in baz_app['ports']
		assert '3:3' in baz_app['ports']
