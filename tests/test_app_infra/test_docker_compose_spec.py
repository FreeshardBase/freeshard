import re
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
			'name': 'baz-app',
			'image': 'baz-app:latest',
			'version': '1.2.3',
			'port': 2,
			'env_vars': {
				'baz-env': 'foo',
				'url': 'https://{{ portal.domain }}/baz'
			},
			'reason': InstallationReason.CUSTOM,
		})

	app_infra.refresh_app_infra()

	with open(Path(gconf.get('path.core')) / 'docker-compose-apps.yml', 'r') as f:
		output = yaml.safe_load(f)
		baz_app = output['services']['baz-app']
		assert 'baz-env=foo' in baz_app['environment']
		assert any(re.search('url=https://.*\.p\.getportal\.org/baz', e) for e in baz_app['environment'])
