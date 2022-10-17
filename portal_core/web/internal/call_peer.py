import logging
from functools import lru_cache
from typing import List

import docker
from docker.models.containers import Container
from fastapi import APIRouter, Request
from starlette.responses import StreamingResponse

from portal_core import signed_request

log = logging.getLogger(__name__)

router = APIRouter()


@router.api_route('/call_peer/{portal_id}/{rest:path}')
def call_peer(portal_id: str, rest: str, request: Request):
	source_host = request.client.host
	app_name = _get_app_for_ip_address(source_host)
	url = f'https://{app_name}.{portal_id}.p.getportal.org/{rest}'

	response = signed_request(request.method, url, stream=True)
	return StreamingResponse(status_code=response.status_code, content=response.iter_content())


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
