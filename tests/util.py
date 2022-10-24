import contextlib
import subprocess
from contextlib import contextmanager
from pathlib import Path

import gconf
from common_py.crypto import PublicKey
from fastapi import Response
from http_message_signatures import HTTPSignatureKeyResolver, algorithms, VerifyResult
from requests import PreparedRequest
from requests_http_signature import HTTPSignatureAuth
from tinydb import where

from portal_core.database.database import apps_table
from portal_core.model.app import AppToInstall
from portal_core.service import app_infra

WAITING_DOCKER_IMAGE = 'nginx:alpine'


def pair_new_terminal(api_client, name='my_terminal', assert_success=True) -> Response:
	pairing_code = get_pairing_code(api_client)
	response = add_terminal(api_client, pairing_code['code'], name)
	if assert_success:
		assert response.status_code == 201
	return response


def get_pairing_code(api_client, deadline=None):
	response = api_client.get('protected/terminals/pairing-code', params={'deadline': deadline})
	assert response.status_code == 201
	return response.json()


def add_terminal(api_client, pairing_code, t_name):
	return api_client.post(
		f'public/pair/terminal?code={pairing_code}',
		json={'name': t_name})


@contextlib.contextmanager
def create_apps_from_docker_compose():
	dc = Path(gconf.get('path_root')) / 'core' / 'docker-compose-apps.yml'
	subprocess.run(
		f'docker-compose -p apps -f {dc.name} up --remove-orphans --no-start',
		cwd=dc.parent,
		shell=True,
		check=True,
	)
	try:
		yield
	finally:
		subprocess.run(
			f'docker-compose -p apps -f {dc.name} down', cwd=dc.parent,
			shell=True,
			check=True,
		)


def verify_signature_auth(request: PreparedRequest, pubkey: PublicKey) -> VerifyResult:
	class KR(HTTPSignatureKeyResolver):
		def resolve_private_key(self, key_id: str):
			pass

		def resolve_public_key(self, key_id: str):
			return pubkey.to_bytes()

	return HTTPSignatureAuth.verify(
		request,
		signature_algorithm=algorithms.RSA_PSS_SHA512,
		key_resolver=KR(),
	)


@contextmanager
def install_test_app():
	with apps_table() as apps:  # type: Table
		apps.truncate()
		apps.insert(AppToInstall(**{
			'description': 'n/a',
			'env_vars': None,
			'image': WAITING_DOCKER_IMAGE,
			'installation_reason': 'config',
			'name': 'myapp',
			'paths': {
				'': {
					'access': 'private',
					'headers': {
						'X-Ptl-Client-Id': '{{ auth.client_id }}',
						'X-Ptl-Client-Name': '{{ auth.client_name }}',
						'X-Ptl-Client-Type': '{{ auth.client_type }}',
						'X-Ptl-ID': '{{ portal.id }}',
						'X-Ptl-Foo': 'bar'
					}
				},
				'/public': {
					'access': 'public',
					'headers': {
						'X-Ptl-Client-Id': '{{ auth.client_id }}',
						'X-Ptl-Client-Name': '{{ auth.client_name }}',
						'X-Ptl-Client-Type': '{{ auth.client_type }}',
						'X-Ptl-ID': '{{ portal.id }}',
						'X-Ptl-Foo': 'baz'
					}
				},
				'/peer': {
					'access': 'peer',
					'headers': {
						'X-Ptl-Client-Id': '{{ auth.client_id }}',
						'X-Ptl-Client-Name': '{{ auth.client_name }}',
						'X-Ptl-Client-Type': '{{ auth.client_type }}',
					}
				}
			},
			'port': 80,
			'services': None,
			'v': '1.0'
		}).dict())
	app_infra.refresh_app_infra()

	with create_apps_from_docker_compose():
		yield

	with apps_table() as apps:
		apps.remove(where('name') == 'myapp')
	app_infra.refresh_app_infra()
