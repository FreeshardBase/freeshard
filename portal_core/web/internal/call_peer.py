import asyncio
import atexit
import logging
from functools import lru_cache
from typing import List

import docker
import httpx
from docker.models.containers import Container
from fastapi import APIRouter, Request, Response

from portal_core.service.signed_call import get_default_signature_auth

log = logging.getLogger(__name__)

router = APIRouter()

client = httpx.AsyncClient()
atexit.register(asyncio.run, client.aclose())


@router.api_route('/call_peer/{portal_id}/{rest}')
async def call_peer(portal_id: str, rest: str, request: Request):
	source_host = request.client.host
	app_name = _get_app_for_ip_address(source_host)
	url = f'https://{app_name}.{portal_id}.p.getportal.org/{rest}'

	async with client.stream(
		method=request.method,
		url=url,
		params=request.query_params,
		auth=get_default_signature_auth(),
		content=request.stream(),
	) as response:
		return Response(
			status_code=response.status,
			content=response.aiter_bytes,
		)


@lru_cache()
def _get_app_for_ip_address(ip_address: str):
	docker_client = _get_docker_client()
	docker_client.networks.get('portal')
	containers: List[Container] = docker_client.containers.list()
	for c in containers:
		if c.attrs['NetworkSettings']['IPAddress'] == ip_address:
			return c.name
	raise RuntimeError(f'no running container found for address {ip_address}')


@lru_cache()
def _get_docker_client():
	return docker.from_env()
