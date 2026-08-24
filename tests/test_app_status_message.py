import pytest
from fastapi import status
from httpx import AsyncClient

from shard_core.data_model.app_meta import InstallationReason, InstalledApp, Status
from shard_core.database import installed_apps as db_installed_apps
from shard_core.database.connection import db_conn
from shard_core.service.app_installation.util import update_app_status

pytest_plugins = ("pytest_asyncio",)
pytestmark = pytest.mark.asyncio


async def _insert_app(name: str):
    async with db_conn() as conn:
        await db_installed_apps.insert(
            conn,
            InstalledApp(
                name=name,
                installation_reason=InstallationReason.CUSTOM,
                status=Status.INSTALLING,
            ).model_dump(),
        )


async def _get_app(name: str) -> InstalledApp:
    async with db_conn() as conn:
        return InstalledApp.model_validate(
            await db_installed_apps.get_by_name(conn, name)
        )


async def test_error_message_is_persisted(db):
    await _insert_app("app_a")

    await update_app_status("app_a", Status.ERROR, message="boom")

    assert (await _get_app("app_a")).status_message == "boom"


async def test_message_is_cleared_when_leaving_error(db):
    await _insert_app("app_b")
    await update_app_status("app_b", Status.ERROR, message="boom")

    await update_app_status("app_b", Status.STOPPED)

    assert (await _get_app("app_b")).status_message is None


async def test_message_ignored_for_non_error_status(db):
    await _insert_app("app_c")
    await update_app_status("app_c", Status.ERROR, message="boom")

    await update_app_status("app_c", Status.STOPPED, message="not an error")

    assert (await _get_app("app_c")).status_message is None


async def test_error_message_survives_reload_via_api(app_client: AsyncClient):
    await _insert_app("app_d")
    await update_app_status("app_d", Status.ERROR, message="install failed: boom")

    single = await app_client.get("protected/apps/app_d")
    assert single.status_code == status.HTTP_200_OK
    assert single.json()["status"] == Status.ERROR
    assert single.json()["status_message"] == "install failed: boom"

    listing = await app_client.get("protected/apps")
    assert listing.status_code == status.HTTP_200_OK
    app_d = next(a for a in listing.json() if a["name"] == "app_d")
    assert app_d["status_message"] == "install failed: boom"
