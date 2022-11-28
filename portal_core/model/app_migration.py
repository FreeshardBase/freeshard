import re
from contextlib import suppress


def migrate_0_0_to_1_0(app_json: dict) -> dict:
	try:
		authentication = app_json['authentication']
	except KeyError:
		app_json['paths'] = {'': {'access': 'private'}}
	else:
		if authentication['default_access'] == 'private':
			app_json['paths'] = {'': {
				'access': 'private',
				'headers': {
					'X-Ptl-Client-Type': 'terminal',
					'X-Ptl-Client-Id': '{{ client_id }}',
					'X-Ptl-Client-Name': '{{ client_name }}'
				}
			}}
		elif authentication['default_access'] == 'public':
			app_json['paths'] = {'': {
				'access': 'public',
				'headers': {
					'X-Ptl-Client-Type': 'public'
				}
			}}

		with suppress(KeyError):
			for private_path in authentication['private_paths'] or []:
				app_json['paths'][private_path] = {
					'access': 'private',
					'headers': {
						'X-Ptl-Client-Type': 'terminal',
						'X-Ptl-Client-Id': '{{ client_id }}',
						'X-Ptl-Client-Name': '{{ client_name }}'
					}
				}

		with suppress(KeyError):
			for public_path in authentication['public_paths'] or []:
				app_json['paths'][public_path] = {
					'access': 'public',
					'headers': {
						'X-Ptl-Client-Type': 'public'
					}
				}
		del app_json['authentication']

	app_json['v'] = '1.0'

	return app_json


def migrate_1_0_to_2_0(app_json: dict) -> dict:
	try:
		description = app_json['description']
	except KeyError:
		pass
	else:
		app_json['store_info'] = {
			'description_short': description
		}
		del app_json['description']

	app_json['v'] = '2.0'
	return app_json


def migrate_2_0_to_3_0(app_json: dict) -> dict:
	name_ = app_json["name"]
	pattern = re.compile(fr'apps\["{name_}"\]\.')
	with suppress(KeyError, AttributeError):
		for k, v in app_json['env_vars'].items():
			sub = pattern.sub('', v)
			app_json['env_vars'][k] = sub

	app_json['v'] = '3.0'
	return app_json


def migrate_3_0_to_3_1(app_json: dict) -> dict:
	app_json['lifecycle'] = {
		'always_on': False,
		'idle_time_for_shutdown': 60,
	}
	app_json['v'] = '3.1'
	return app_json


def migrate_3_1_to_3_2(app_json: dict) -> dict:
	"""
	Nothing needs to be done because the *shared_dirs* field is optional.
	"""
	app_json['v'] = '3.2'
	return app_json


def migrate_3_2_to_4_0(app_json: dict) -> dict:
	https_port = app_json['port']
	del app_json['port']
	app_json['entrypoints'] = [{'container_port': https_port, 'entrypoint_port': 'http'}]
	app_json['v'] = '4.0'
	return app_json


migrations = {
	'0.0': migrate_0_0_to_1_0,
	'1.0': migrate_1_0_to_2_0,
	'2.0': migrate_2_0_to_3_0,
	'3.0': migrate_3_0_to_3_1,
	'3.1': migrate_3_1_to_3_2,
	'3.2': migrate_3_2_to_4_0,
}
