import re

import gconf
import pytest
import yaml

from portal_core.database.database import apps_table
from portal_core.model.app import InstallationReason
from portal_core.service import identity, app_infra

pytestmark = pytest.mark.usefixtures('tempfile_path_config')


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

	with open(gconf.get('app_infra.compose_filename'), 'r') as f:
		output = yaml.safe_load(f)
		baz_app = output['services']['baz-app']
		assert 'baz-env=foo' in baz_app['environment']
		assert any(re.search('url=https://.*\.p\.getportal\.org/baz', e) for e in baz_app['environment'])
