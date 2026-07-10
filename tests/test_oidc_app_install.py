"""OIDC client registration during app installation.

Uses the oidc_app from the mock app store, whose app_meta.json declares an
oidc section and whose compose template consumes {{ oidc.* }} variables.
"""

from httpx import AsyncClient

from shard_core.database.connection import db_conn
from shard_core.database import oidc as db_oidc
from shard_core.service.app_tools import get_installed_apps_path
from tests.util import wait_until_app_installed, wait_until_app_uninstalled

APP_NAME = "oidc_app"


async def _get_client_row() -> dict | None:
    async with db_conn() as conn:
        return await db_oidc.get_client_by_app_name(conn, APP_NAME)


async def _install(api_client: AsyncClient):
    response = await api_client.post(f"protected/apps/{APP_NAME}")
    assert response.status_code == 201
    await wait_until_app_installed(api_client, APP_NAME)


async def test_install_registers_client_and_renders_creds(api_client: AsyncClient):
    await _install(api_client)

    row = await _get_client_row()
    assert row is not None
    assert row["client_secret"]

    domain = (await api_client.get("public/meta/whoareyou")).json()["domain"]
    assert row["redirect_uris"] == [f"https://{APP_NAME}.{domain}/callback"]

    compose = (get_installed_apps_path() / APP_NAME / "docker-compose.yml").read_text()
    assert f"OIDC_CLIENT_ID={row['client_id']}" in compose
    assert f"OIDC_CLIENT_SECRET={row['client_secret']}" in compose
    assert f"OIDC_ISSUER=https://{domain}/core/public/oidc" in compose


async def test_reinstall_keeps_client_credentials(api_client: AsyncClient):
    await _install(api_client)
    before = await _get_client_row()

    response = await api_client.post(f"protected/apps/{APP_NAME}/reinstall")
    assert response.status_code == 201
    await wait_until_app_installed(api_client, APP_NAME)

    after = await _get_client_row()
    assert after["client_id"] == before["client_id"]
    assert after["client_secret"] == before["client_secret"]


async def test_uninstall_removes_client(api_client: AsyncClient):
    await _install(api_client)
    assert await _get_client_row() is not None

    response = await api_client.delete(f"protected/apps/{APP_NAME}")
    assert response.status_code in (200, 204)
    await wait_until_app_uninstalled(api_client, APP_NAME)

    assert await _get_client_row() is None
