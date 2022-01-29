import re
from pathlib import Path

import gconf
import psycopg
import pytest
import yaml

from portal_core.database import apps_table
from portal_core.model.app import InstallationReason
from portal_core.service import compose, identity

pytestmark = pytest.mark.usefixtures('tempfile_path_config')


def test_data_dirs_are_created():
    identity.init_default_identity()
    with apps_table() as apps:
        apps.insert({
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

    compose.refresh_docker_compose()

    assert (Path(gconf.get('apps.app_data_dir')) / 'foo-app' / 'user_data' / 'foo').is_dir()
    assert (Path(gconf.get('apps.app_data_dir')) / 'foo-app' / 'user_data' / 'bar').is_dir()


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

    compose.refresh_docker_compose()

    with open(gconf.get('docker_compose.compose_filename'), 'r') as f:
        output = yaml.safe_load(f)
        baz_app = output['services']['baz-app']
        assert 'baz-env=foo' in baz_app['environment']
        assert any(re.search('url=https://.*\.p\.getportal\.org/baz', e) for e in baz_app['environment'])


def test_postgres_is_setup(postgres):
    identity.init_default_identity()
    with apps_table() as apps:
        apps.insert({
            'name': 'postgres-app',
            'image': 'postgres-app:latest',
            'version': '1.2.3',
            'port': 2,
            'services': ['postgres'],
            'reason': InstallationReason.CUSTOM,
        })

    compose.refresh_docker_compose()

    with psycopg.connect(gconf.get('services.postgres.connection_string')) as conn:
        with conn.cursor() as cur:
            dbs = cur.execute('SELECT datname FROM pg_database')
            assert ('postgres-app',) in dbs
