import asyncio
import logging
from fastapi import APIRouter, Request

from shard_core.service.signed_call import signed_request
from shard_core.settings import settings
from shard_core.web.util import ALL_HTTP_METHODS
from starlette.responses import StreamingResponse

log = logging.getLogger(__name__)

router = APIRouter()


async def async_iter_content(response, chunk_size=8192):
    iterator = response.iter_content(chunk_size=chunk_size)
    while True:
        chunk = await asyncio.to_thread(next, iterator, None)
        if chunk is None:
            break
        yield chunk


@router.api_route("/call_backend/{rest:path}", methods=ALL_HTTP_METHODS)
async def call_backend(rest: str, request: Request):
    base_url = settings().freeshard_controller.base_url
    url = f"{base_url}/{rest}"

    body = await request.body()
    response = await signed_request(
        request.method, url, data=body, params=dict(request.query_params)
    )

    log.debug(f"called backend: {url} -> {response.status_code}")

    return StreamingResponse(
        status_code=response.status_code,
        headers=response.headers,
        content=async_iter_content(response, chunk_size=8192),
    )
