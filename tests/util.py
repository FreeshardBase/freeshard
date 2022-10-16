import contextlib
import subprocess
from pathlib import Path

import gconf
from common_py.crypto import PublicKey
from http_message_signatures import HTTPSignatureKeyResolver, algorithms, VerifyResult
from requests import PreparedRequest
from requests_http_signature import HTTPSignatureAuth
from fastapi import Response

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
