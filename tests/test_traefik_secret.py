from pathlib import Path

import yaml
from httpx import AsyncClient
from starlette import status

from shard_core.service import traefik_secret
from shard_core.service.app_installation.util import write_traefik_dyn_config
from shard_core.settings import settings


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
