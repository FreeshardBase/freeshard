import logging
from fastapi import APIRouter, Request

from shard_core.service.signed_call import signed_request
from shard_core.web.util import ALL_HTTP_METHODS
from starlette.responses import StreamingResponse

import gconf

log = logging.getLogger(__name__)

router = APIRouter()


@router.api_route("/call_backend/{rest:path}", methods=ALL_HTTP_METHODS)
async def call_backend(rest: str, request: Request):
    base_url = gconf.get("freeshard_controller.base_url")
    url = f"{base_url}/{rest}"

    body = await request.body()
    response = await signed_request(request.method, url, data=body)

    log.debug(f"called backend: {url} -> {response.status_code}")

    return StreamingResponse(
        status_code=response.status_code,
        headers=response.headers,
        content=response.iter_content(),
    )
