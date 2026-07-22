from pathlib import Path

import yaml
from httpx import AsyncClient
from starlette import status

from shard_core.database import database
from shard_core.service import traefik_secret
from shard_core.service.app_installation.util import write_traefik_dyn_config
from shard_core.settings import settings


async def _drive_ws_handshake(app_client: AsyncClient, path: str) -> list[str]:
    """Open a websocket against the ASGI app behind app_client using the client's
    current headers, and return the ASGI message types the app sent back."""
    app = app_client._transport.app
    sent: list[dict] = []
    received = {"n": 0}

    async def receive():
        received["n"] += 1
        if received["n"] == 1:
            return {"type": "websocket.connect"}
        return {"type": "websocket.disconnect", "code": 1000}

    async def send(message):
        sent.append(message)

    scope = {
        "type": "websocket",
        "path": path,
        "raw_path": path.encode(),
        "headers": [(k.encode(), v.encode()) for k, v in app_client.headers.items()],
        "query_string": b"",
        "scheme": "ws",
        "subprotocols": [],
        "client": ("10.0.0.9", 1234),
        "server": ("shard_core", 80),
    }
    await app(scope, receive, send)
    return [m["type"] for m in sent]


def _read_traefik_dyn() -> dict:
    with open(
        Path(settings().path_root) / "core" / "traefik_dyn" / "traefik_dyn.yml", "r"
    ) as f:
        return yaml.safe_load(f)


async def test_protected_without_secret_is_rejected(app_client: AsyncClient):
    del app_client.headers[traefik_secret.HEADER_NAME]

    response = await app_client.get("protected/terminals")

    assert response.status_code == status.HTTP_403_FORBIDDEN


async def test_protected_with_wrong_secret_is_rejected(app_client: AsyncClient):
    app_client.headers[traefik_secret.HEADER_NAME] = "not-the-real-secret"

    response = await app_client.get("protected/terminals")

    assert response.status_code == status.HTTP_403_FORBIDDEN


async def test_protected_with_secret_is_allowed(app_client: AsyncClient):
    response = await app_client.get("protected/terminals")

    assert response.status_code == status.HTTP_200_OK


async def test_management_without_secret_is_rejected(app_client: AsyncClient):
    del app_client.headers[traefik_secret.HEADER_NAME]

    response = await app_client.get("management/pairing_code")

    assert response.status_code == status.HTTP_403_FORBIDDEN


async def test_management_with_secret_is_allowed(app_client: AsyncClient):
    response = await app_client.get("management/pairing_code")

    assert response.status_code == status.HTTP_200_OK


async def test_public_needs_no_secret(app_client: AsyncClient):
    del app_client.headers[traefik_secret.HEADER_NAME]

    response = await app_client.get("public/meta/whoareyou")

    assert response.status_code == status.HTTP_200_OK


async def test_forward_auth_endpoint_is_not_gated_by_secret(app_client: AsyncClient):
    # Traefik calls the forwardAuth endpoints directly (no verify-traefik middleware
    # in the chain), so they must reject on their own auth (401), not the secret gate.
    del app_client.headers[traefik_secret.HEADER_NAME]

    response = await app_client.get("internal/authenticate_terminal")

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


async def test_missing_secret_fails_closed_with_500(app_client: AsyncClient):
    # A shard whose secret somehow never got stored must fail closed, not open.
    await database.remove_value(traefik_secret.STORE_KEY_TRAEFIK_SECRET)

    response = await app_client.get("protected/terminals")

    assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR


async def test_protected_websocket_rejected_without_secret(app_client: AsyncClient):
    # The /protected/ws/updates stream must not be openable by an app connecting
    # directly (bypassing Traefik). Without the secret the handshake is denied, so the
    # app never sees a websocket.accept.
    del app_client.headers[traefik_secret.HEADER_NAME]

    sent_types = await _drive_ws_handshake(app_client, "/protected/ws/updates")

    assert "websocket.accept" not in sent_types


async def test_protected_websocket_accepts_with_secret(app_client: AsyncClient):
    # Positive control: with the Traefik-injected secret the same handshake is accepted.
    # This is what makes the rejection test above meaningful rather than decorative.
    sent_types = await _drive_ws_handshake(app_client, "/protected/ws/updates")

    assert "websocket.accept" in sent_types


async def test_traefik_config_injects_secret_on_sensitive_routers(app_client):
    await write_traefik_dyn_config()
    stored_secret = await traefik_secret.get_traefik_secret()
    config = _read_traefik_dyn()

    middleware = config["http"]["middlewares"]["verify-traefik"]
    assert middleware["headers"]["customRequestHeaders"] == {
        traefik_secret.HEADER_NAME: stored_secret
    }

    routers = config["http"]["routers"]
    assert "verify-traefik" in routers["shard_core_private"]["middlewares"]
    assert "verify-traefik" in routers["shard_core_management"]["middlewares"]
    assert "verify-traefik" not in routers["shard_core_public"]["middlewares"]
