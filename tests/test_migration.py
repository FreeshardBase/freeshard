from tinydb import Query
from tinydb.table import Table

from portal_core.database import migration, database

v0_0_app_json = {
	'name': 'filebrowser',
	'description': 'n/a',
	'env_vars': {
		'DATABASE_URL': '{{ apps[\"filebrowser\"].postgres.connection_string }}'
	},
	'image': 'portalapps.azurecr.io/ptl-apps/filebrowser:master',
	'port': 80,
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
	'services': None,
	'installation_reason': 'config',
}

v1_0_app_json = {
	'v': '1.0',
	'name': 'filebrowser',
	'description': 'n/a',
	'env_vars': {
		'DATABASE_URL': '{{ apps[\"filebrowser\"].postgres.connection_string }}'
	},
	'image': 'portalapps.azurecr.io/ptl-apps/filebrowser:master',
	'port': 80,
	'paths': {
		'': {
			'access': 'private',
			'headers': {
				'X-Ptl-Client-Id': '{{ client_id }}',
				'X-Ptl-Client-Name': '{{ client_name }}',
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
	'data_dirs': [
		'/data'
	],
	'services': None,
	'installation_reason': 'config',
}

v2_0_app_json = {
	'v': '2.0',
	'name': 'filebrowser',
	'env_vars': {
		'DATABASE_URL': '{{ apps[\"filebrowser\"].postgres.connection_string }}'
	},
	'image': 'portalapps.azurecr.io/ptl-apps/filebrowser:master',
	'port': 80,
	'paths': {
		'': {
			'access': 'private',
			'headers': {
				'X-Ptl-Client-Id': '{{ client_id }}',
				'X-Ptl-Client-Name': '{{ client_name }}',
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
	'data_dirs': [
		'/data'
	],
	'postgres': None,
	'status': 'unknown',
	'store_info': {
		'description_long': None,
		'description_short': 'n/a',
		'hint': None,
		'is_featured': None},
	'services': None,
	'installation_reason': 'config',
}

v3_2_app_json = {
	'v': '3.2',
	'name': 'filebrowser',
	'env_vars': {
		'DATABASE_URL': '{{ postgres.connection_string }}'
	},
	'image': 'portalapps.azurecr.io/ptl-apps/filebrowser:master',
	'port': 80,
	'paths': {
		'': {
			'access': 'private',
			'headers': {
				'X-Ptl-Client-Id': '{{ client_id }}',
				'X-Ptl-Client-Name': '{{ client_name }}',
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
	'data_dirs': [
		'/data'
	],
	'lifecycle': {
		'always_on': False,
		'idle_time_for_shutdown': 60,
	},
	'postgres': None,
	'status': 'unknown',
	'store_info': {
		'description_long': None,
		'description_short': 'n/a',
		'hint': None,
		'is_featured': None},
	'services': None,
	'installation_reason': 'config',
}


def test_app_needs_migration():
	assert migration._needs_migration({'foo': 2, 'bar': 3})
	assert migration._needs_migration({'v': '0.0', 'foo': 2, 'bar': 3})
	assert migration._needs_migration({'v': '1.0', 'foo': 2, 'bar': 3})
	assert migration._needs_migration({'v': '2.0', 'foo': 2, 'bar': 3})
	assert migration._needs_migration({'v': '3.0', 'foo': 2, 'bar': 3})
	assert migration._needs_migration({'v': '3.1', 'foo': 2, 'bar': 3})
	assert not migration._needs_migration({'v': '3.2', 'foo': 2, 'bar': 3})


def test_migration_from_0_0(init_db):
	with database.apps_table() as apps:  # type: Table
		apps.insert(v0_0_app_json)

	with database.apps_table() as apps:  # type: Table
		assert apps.get(Query().name == 'filebrowser') == v0_0_app_json

	migration.migrate_all()

	with database.apps_table() as apps:  # type: Table
		assert apps.get(Query().name == 'filebrowser') == v3_2_app_json


def test_migration_from_1_0(init_db):
	with database.apps_table() as apps:  # type: Table
		apps.insert(v1_0_app_json)

	with database.apps_table() as apps:  # type: Table
		assert apps.get(Query().name == 'filebrowser') == v1_0_app_json

	migration.migrate_all()

	with database.apps_table() as apps:  # type: Table
		assert apps.get(Query().name == 'filebrowser') == v3_2_app_json
