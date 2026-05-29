"""Tests for the app_proxy internal endpoint.

The proxy sits between Traefik and app containers and captures the original
error response body, embedding it in the splash HTML for developer inspection.
"""

import json
from unittest.mock import AsyncMock, MagicMock

import httpx
from starlette import status

from shard_core.web.internal.app_error import build_upstream_json
from tests.util import install_app

# ---------------------------------------------------------------------------
# build_upstream_json unit tests (no HTTP involved)
# ---------------------------------------------------------------------------


def test_build_upstream_json_basic():
    result = build_upstream_json(
        status=422,
        content_type="application/json",
        body='{"detail": [{"msg": "field required"}]}',
    )
    parsed = json.loads(result)
    assert parsed["status"] == 422
    assert parsed["content_type"] == "application/json"
    assert "field required" in parsed["body"]


def test_build_upstream_json_no_content_type():
    result = build_upstream_json(status=500, content_type=None, body="Internal Error")
    parsed = json.loads(result)
    assert parsed["status"] == 500
    assert parsed["content_type"] is None
    assert parsed["body"] == "Internal Error"


def test_build_upstream_json_escapes_script_tag():
    """Ensure </script> in the body cannot close the embedding <script> tag."""
    body = "hack</script><script>alert(1)</script>"
    result = build_upstream_json(status=200, content_type="text/html", body=body)
    assert "</script>" not in result
    # The JSON is still valid and the body is recoverable.
    parsed = json.loads(result)
    assert parsed["body"] == body


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_upstream_response(
    status_code: int,
    body: str,
    content_type: str = "application/json",
) -> MagicMock:
    """Build a fake httpx.Response-like mock."""
    response = MagicMock(spec=httpx.Response)
    response.status_code = status_code
    response.headers = httpx.Headers({"content-type": content_type})
    response.text = body
    response.content = body.encode()
    return response


def _mock_client(response: MagicMock):
    """Return a context-manager mock that yields a client whose request() returns *response*."""
    client = AsyncMock()
    client.request = AsyncMock(return_value=response)
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=client)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


# ---------------------------------------------------------------------------
# Integration tests for the proxy endpoint
# ---------------------------------------------------------------------------


async def test_proxy_error_response_embeds_upstream_body(api_client, mocker):
    """When the app returns a 4xx error, the splash contains the upstream body."""
    await install_app(api_client, "mock_app")

    upstream_body = (
        '{"detail": [{"loc": ["body", "name"], "msg": "field required",'
        ' "type": "value_error.missing"}]}'
    )
    fake_response = _make_upstream_response(422, upstream_body)
    mocker.patch(
        "shard_core.web.internal.app_proxy.httpx.AsyncClient",
        return_value=_mock_client(fake_response),
    )

    response = await api_client.get(
        "internal/app_proxy/api/shards/1/update",
        headers={"host": "mock_app.myshard.org"},
    )

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    html = response.text
    assert 'id="upstream-response"' in html

    # The embedded JSON should contain the original status and body.
    script_start = html.index('id="upstream-response">')
    script_end = html.index("</script>", script_start)
    embedded = html[script_start + len('id="upstream-response">') : script_end]
    parsed = json.loads(embedded)
    assert parsed["status"] == 422
    assert "field required" in parsed["body"]
    assert parsed["content_type"] == "application/json"


async def test_proxy_success_passes_through(api_client, mocker):
    """For 2xx responses the proxy passes through the response without a splash."""
    await install_app(api_client, "mock_app")

    fake_response = _make_upstream_response(200, '{"result": "ok"}')
    mocker.patch(
        "shard_core.web.internal.app_proxy.httpx.AsyncClient",
        return_value=_mock_client(fake_response),
    )

    response = await api_client.get(
        "internal/app_proxy/api/data",
        headers={"host": "mock_app.myshard.org"},
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {"result": "ok"}
    # No splash rendered for successful responses.
    assert "upstream-response" not in response.text


async def test_proxy_connection_error_shows_splash_without_upstream(api_client, mocker):
    """When the app container is unreachable the splash shows without upstream data."""
    await install_app(api_client, "mock_app")

    client_mock = AsyncMock()
    client_mock.request = AsyncMock(
        side_effect=httpx.ConnectError("Connection refused")
    )
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=client_mock)
    cm.__aexit__ = AsyncMock(return_value=False)
    mocker.patch(
        "shard_core.web.internal.app_proxy.httpx.AsyncClient",
        return_value=cm,
    )

    response = await api_client.get(
        "internal/app_proxy/",
        headers={"host": "mock_app.myshard.org"},
    )

    assert response.status_code == status.HTTP_502_BAD_GATEWAY
    html = response.text
    assert "mock_app" in html
    # No upstream data when the container is unreachable.
    assert 'id="upstream-response"' not in html


async def test_proxy_500_error_shows_splash_with_upstream_body(api_client, mocker):
    """Server errors (5xx) also embed the upstream body in the splash."""
    await install_app(api_client, "mock_app")

    upstream_body = "Internal Server Error: unhandled exception in view"
    fake_response = _make_upstream_response(
        500, upstream_body, content_type="text/plain"
    )
    mocker.patch(
        "shard_core.web.internal.app_proxy.httpx.AsyncClient",
        return_value=_mock_client(fake_response),
    )

    response = await api_client.get(
        "internal/app_proxy/crash",
        headers={"host": "mock_app.myshard.org"},
    )

    assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    html = response.text
    assert 'id="upstream-response"' in html
    script_start = html.index('id="upstream-response">')
    script_end = html.index("</script>", script_start)
    embedded = html[script_start + len('id="upstream-response">') : script_end]
    parsed = json.loads(embedded)
    assert parsed["status"] == 500
    assert parsed["body"] == upstream_body
