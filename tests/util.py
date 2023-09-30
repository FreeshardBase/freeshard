import asyncio
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

from common_py.crypto import PublicKey
from fastapi import Response
from http_message_signatures import HTTPSignatureKeyResolver, algorithms, VerifyResult
from httpx import AsyncClient
from httpx import URL, Request
from requests import PreparedRequest
from requests_http_signature import HTTPSignatureAuth

from portal_core.model.app_meta import InstalledApp, Status
from portal_core.util.subprocess import subprocess

WAITING_DOCKER_IMAGE = 'nginx:alpine'


async def pair_new_terminal(api_client, name='my_terminal', assert_success=True) -> Response:
	pairing_code = await get_pairing_code(api_client)
	response = await add_terminal(api_client, pairing_code['code'], name)
	if assert_success:
		assert response.status_code == 201
	return response


async def get_pairing_code(api_client: AsyncClient, deadline=None):
	params = {'deadline': deadline} if deadline else {}
	response = await api_client.get('protected/terminals/pairing-code', params=params)
	response.raise_for_status()
	return response.json()


async def add_terminal(api_client, pairing_code, t_name):
	return await api_client.post(
		f'public/pair/terminal?code={pairing_code}',
		json={'name': t_name})


async def wait_until_app_installed(api_client: AsyncClient, app_name):
	while True:
		app = InstalledApp.parse_obj((await api_client.get(f'protected/apps/{app_name}')).json())
		if app.status in (Status.INSTALLING, Status.INSTALLATION_QUEUED):
			await asyncio.sleep(2)
		elif app.status in (Status.STOPPED, Status.RUNNING):
			return app
		else:
			raise AssertionError(f'Unexpected app status: {app.status}')


async def wait_until_all_apps_installed(async_client: AsyncClient):
	while True:
		apps = (await async_client.get('protected/apps')).json()
		if any(app['status'] in (Status.INSTALLING, Status.INSTALLATION_QUEUED) for app in apps):
			await asyncio.sleep(2)
		else:
			return


def mock_app_store_path():
	return Path(__file__).parent / 'mock_app_store'


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


async def retry_async(f: Callable, timeout: int = 90, frequency: int = 3, retry_errors=None):
	if not retry_errors:
		retry_errors = [AssertionError]

	end = time.time() + timeout
	last_error = None
	result = None
	while time.time() < end:
		try:
			result = await f()
		except Exception as e:
			if type(e) in retry_errors:
				last_error = e
			else:
				raise e
		else:
			last_error = None
			break

		await asyncio.sleep(frequency)

	if last_error:
		raise last_error

	return result
