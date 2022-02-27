from tinydb import Query
from tinydb.table import Table

from portal_core.database import migration, database


def test_app_needs_migration():
	assert migration._needs_migration({'foo': 2, 'bar': 3})
	assert migration._needs_migration({'v': '0.0', 'foo': 2, 'bar': 3})
	assert not migration._needs_migration({'v': '1.0', 'foo': 2, 'bar': 3})


def test_migration(init_db):
	legacy_app_json = {
		'authentication': {
			'default_access': 'private',
			'peer_paths': None,
			'private_paths': None,
			'public_paths': [
				'/share/',
				'/static/',
				'/api/public/'
			]
		},
		'data_dirs': [
			'/data'
		],
		'description': 'n/a',
		'env_vars': None,
		'image': 'portalapps.azurecr.io/ptl-apps/filebrowser:master',
		'installation_reason': 'config',
		'name': 'filebrowser',
		'port': 80,
		'services': None
	}

	current_app_json = {
		'data_dirs': [
			'/data'
		],
		'description': 'n/a',
		'env_vars': None,
		'image': 'portalapps.azurecr.io/ptl-apps/filebrowser:master',
		'installation_reason': 'config',
		'name': 'filebrowser',
		'paths': {
			'': {
				'access': 'private',
				'headers': {
					'X-Ptl-Client-Id': '{{ client_id }}',
					'X-Ptl-Client-Type': 'terminal'
				}
			},
			'/api/public/': {
				'access': 'public',
				'headers': {
					'X-Ptl-Client-Type': 'public'
				}
			},
			'/share/': {
				'access': 'public',
				'headers': {
					'X-Ptl-Client-Type': 'public'
				}
			},
			'/static/': {
				'access': 'public',
				'headers': {
					'X-Ptl-Client-Type': 'public'
				}
			}
		},
		'port': 80,
		'postgres': None,
		'services': None,
		'status': 'unknown',
		'v': '1.0'
	}

	up_to_date_app = {
		'data_dirs': [
			'/data'
		],
		'description': 'n/a',
		'env_vars': None,
		'image': 'foo:master',
		'installation_reason': 'config',
		'name': 'foo',
		'paths': {
			'': {
				'access': 'private',
				'headers': {
					'X-Ptl-Client-Id': '{{ client_id }}',
					'X-Ptl-Client-Type': 'terminal'
				}
			},
			'/api/public/': {
				'access': 'public',
				'headers': {
					'X-Ptl-Client-Type': 'public'
				}
			},
		},
		'port': 80,
		'postgres': None,
		'services': None,
		'status': 'unknown',
		'v': '1.0'
	}

	with database.apps_table() as apps:  # type: Table
		apps.insert(legacy_app_json)
		apps.insert(up_to_date_app)

	with database.apps_table() as apps:  # type: Table
		assert apps.get(Query().name == 'filebrowser') == legacy_app_json
		assert apps.get(Query().name == 'foo') == up_to_date_app

	migration.migrate_all()

	with database.apps_table() as apps:  # type: Table
		assert apps.get(Query().name == 'filebrowser') == current_app_json
		assert apps.get(Query().name == 'foo') == up_to_date_app
