"""Reverse proxy that sits between Traefik and app containers.

Traefik routes app-subdomain traffic here (via the `app-proxy-prefix`
addPrefix middleware) instead of directly to each app container.  This lets
shard_core capture the full upstream response body so it can be embedded,
hidden, in the splash HTML for developer inspection.

For non-error responses the body is streamed through unchanged.
For 4xx / 5xx responses the upstream body is captured, embedded in a hidden
<script type="application/json" id="upstream-response"> element inside the
splash page, and the splash is returned to the client.
"""

import logging
from typing import Optional

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response

from shard_core.data_model.app_meta import EntrypointPort
from shard_core.service.app_tools import get_app_metadata, MetadataNotFound
from shard_core.web.internal.app_error import (
    build_upstream_json,
    get_container_status,
    make_splash_behaviour_for_proxy,
    render_splash_response,
)
from shard_core.web.util import ALL_HTTP_METHODS

log = logging.getLogger(__name__)

router = APIRouter()

# Headers that must not be forwarded to the upstream app container.
# These are either hop-by-hop headers or headers that httpx manages itself.
_SKIP_REQUEST_HEADERS = frozenset(
    {
        "host",
        "connection",
        "keep-alive",
        "transfer-encoding",
        "te",
        "trailers",
        "upgrade",
        "proxy-authorization",
        "proxy-connection",
        "content-length",  # httpx recalculates this
    }
)

# Headers from the upstream response that must not be forwarded to the client.
_SKIP_RESPONSE_HEADERS = frozenset(
    {
        "connection",
        "keep-alive",
        "transfer-encoding",
        "te",
        "trailers",
        "content-encoding",  # httpx decodes compressed responses automatically
    }
)


@router.api_route("/app_proxy/{path:path}", methods=ALL_HTTP_METHODS)
async def app_proxy(path: str, request: Request) -> Response:
    """Proxy a request to the appropriate app container.

    On error responses the original body is embedded (hidden) in the splash
    page so developers can inspect it via browser dev tools.
    """
    host_header: str = request.headers.get("host", "")
    app_name = host_header.split(".")[0]

    # Resolve the app's HTTP entrypoint from its metadata.
    try:
        app_meta = get_app_metadata(app_name)
    except MetadataNotFound:
        log.warning(f"app_proxy: metadata not found for app {app_name!r}")
        return await _splash(app_name=app_name, status_code=404, upstream_json=None)

    entrypoint = next(
        (
            ep
            for ep in app_meta.entrypoints
            if ep.entrypoint_port == EntrypointPort.HTTPS_443
        ),
        None,
    )
    if entrypoint is None:
        log.warning(f"app_proxy: no HTTP entrypoint for app {app_name!r}")
        return await _splash(app_name=app_name, status_code=502, upstream_json=None)

    target_base = f"http://{entrypoint.container_name}:{entrypoint.container_port}"
    target_url = f"{target_base}/{path}"
    if request.url.query:
        target_url += f"?{request.url.query}"

    # Filter request headers before forwarding.
    forward_headers = {
        k: v
        for k, v in request.headers.items()
        if k.lower() not in _SKIP_REQUEST_HEADERS
    }

    request_body = await request.body()

    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=False) as client:
            upstream = await client.request(
                method=request.method,
                url=target_url,
                headers=forward_headers,
                content=request_body,
            )
    except httpx.ConnectError:
        log.debug(f"app_proxy: connection refused for {app_name!r} at {target_url!r}")
        return await _splash(app_name=app_name, status_code=502, upstream_json=None)
    except httpx.TimeoutException:
        log.debug(f"app_proxy: timeout for {app_name!r} at {target_url!r}")
        return await _splash(app_name=app_name, status_code=504, upstream_json=None)
    except httpx.HTTPError as exc:
        log.warning(f"app_proxy: HTTP error for {app_name!r}: {exc}")
        return await _splash(app_name=app_name, status_code=502, upstream_json=None)

    if upstream.status_code >= 400:
        # Error path: embed the original response body in the splash HTML.
        try:
            body_text = upstream.text
        except Exception:
            body_text = upstream.content.decode("utf-8", errors="replace")

        upstream_json = build_upstream_json(
            status=upstream.status_code,
            content_type=upstream.headers.get("content-type"),
            body=body_text,
        )
        return await _splash(
            app_name=app_name,
            status_code=upstream.status_code,
            upstream_json=upstream_json,
        )

    # Success path: pass the response through.
    response_headers = {
        k: v
        for k, v in upstream.headers.items()
        if k.lower() not in _SKIP_RESPONSE_HEADERS
    }
    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        headers=response_headers,
    )


async def _splash(
    app_name: str,
    status_code: int,
    upstream_json: Optional[str],
) -> HTMLResponse:
    """Render the splash page, optionally with embedded upstream response data."""
    container_status = get_container_status(app_name)
    behaviour = await make_splash_behaviour_for_proxy(
        app_name=app_name,
        status_code=status_code,
        container_status=container_status,
        upstream_json=upstream_json,
    )
    return render_splash_response(behaviour, status_code)
