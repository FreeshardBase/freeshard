from contextlib import asynccontextmanager
from urllib.parse import urlparse

from common_py.crypto import PublicKey
from fastapi import Response
from http_message_signatures import HTTPSignatureKeyResolver, algorithms, VerifyResult
from httpx import URL, Request
from requests import PreparedRequest
from requests_http_signature import HTTPSignatureAuth
from starlette.testclient import TestClient

from portal_core.util.subprocess import subprocess

WAITING_DOCKER_IMAGE = 'nginx:alpine'


def pair_new_terminal(api_client, name='my_terminal', assert_success=True) -> Response:
	pairing_code = get_pairing_code(api_client)
	response = add_terminal(api_client, pairing_code['code'], name)
	if assert_success:
		assert response.status_code == 201
	return response


def get_pairing_code(api_client: TestClient, deadline=None):
	params = {'deadline': deadline} if deadline else {}
	response = api_client.get('protected/terminals/pairing-code', params=params)
	response.raise_for_status()
	return response.json()


def add_terminal(api_client, pairing_code, t_name):
	return api_client.post(
		f'public/pair/terminal?code={pairing_code}',
		json={'name': t_name})


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


def modify_request_like_traefik_forward_auth(request: PreparedRequest) -> Request:
	url = urlparse(request.url)
	netloc_without_subdomain = url.netloc.split('.', maxsplit=1)[1]
	return Request(
		method=request.method,
		url=URL(f'https://{netloc_without_subdomain}/internal/auth'),
		headers={
			'X-Forwarded-Proto': url.scheme,
			'X-Forwarded-Host': url.netloc,
			'X-Forwarded-Uri': url.path,
			'X-Forwarded-Method': request.method,
			'signature-input': request.headers['signature-input'],
			'signature': request.headers['signature'],
			'date': request.headers['date'],
		}
	)


@asynccontextmanager
async def docker_network_portal():
	await subprocess('docker', 'network', 'create', 'portal')
	try:
		yield
	finally:
		await subprocess('docker', 'network', 'rm', 'portal')
