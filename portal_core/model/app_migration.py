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
					'X-Ptl-Client-Id': '{{ client_id }}'
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
			for public_path in authentication['public_paths']:
				app_json['paths'][public_path] = {
					'access': 'public',
					'headers': {
						'X-Ptl-Client-Type': 'public'
					}
				}
		with suppress(KeyError):
			for private_path in authentication['private_paths']:
				app_json['paths'][private_path] = {
					'access': 'private',
					'headers': {
						'X-Ptl-Client-Type': 'terminal',
						'X-Ptl-Client-Id': '{{ client_id }}',
						'X-Ptl-Client-Name': '{{ client_name }}'
					}
				}
		del app_json['authentication']

	app_json['v'] = '1.0'

	return app_json


migrations = {
	'0.0': migrate_0_0_to_1_0
}
