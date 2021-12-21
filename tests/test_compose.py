import re
from pathlib import Path

import gconf
import yaml

from portal_core.database import get_db
from portal_core.model import InstallationReason
from portal_core.service import compose


def test_template(tempfile_path_config):
	with get_db() as db:
		db.table('apps').insert({
			'name': 'foo-app',
			'image': 'foo-app:latest',
			'version': '1.2.3',
			'port': 1,
			'data_dirs': [
				'/user_data/foo',
				'user_data/bar/'
			],
			'authentication': {
				'default_access': 'public',
			},
			'reason': InstallationReason.CUSTOM,
		})
		db.table('apps').insert({
			'name': 'bar-app',
			'image': 'bar-app:latest',
			'version': '4.5.6',
			'port': 2,
			'authentication': {
				'public_paths': ['/foo/'],
				'peer_paths': ['/peer', 'bar'],
			},
			'reason': InstallationReason.CUSTOM,
		})
		db.table('apps').insert({
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

	compose.refresh_docker_compose()

	assert (Path(gconf.get('apps.app_data_dir')) / 'foo-app' / 'user_data' / 'foo').is_dir()
	assert (Path(gconf.get('apps.app_data_dir')) / 'foo-app' / 'user_data' / 'bar').is_dir()

	with open(gconf.get('docker_compose.compose_filename'), 'r') as f:
		output = yaml.load(f)
		baz_app = output['services']['baz-app']
		assert 'baz-env=foo' in baz_app['environment']
		assert any(re.search('url=https://.*\.p\.getportal\.org/baz', e) for e in baz_app['environment'])
