import importlib

import pytest
from asgi_lifespan import LifespanManager

from shard_core import app_factory
from shard_core.data_model.app_meta import InstallationReason, InstalledApp, Status
from shard_core.database import database
from shard_core.database import installed_apps as db_installed_apps
from shard_core.database.connection import db_conn
from shard_core.service import app_installation, telemetry, websocket
from tests.util import docker_network_portal, retry_async

pytest_plugins = ("pytest_asyncio",)
pytestmark = pytest.mark.asyncio

config_override = {"apps": {"initial_apps": []}}

APP_NAME = "mock_app"


async def _seed_interrupted_uninstall(status: Status):
    """Leave behind exactly what a stop mid-uninstall leaves: a row in an
    uninstalling status, no files on disk, and nothing in the task queue."""
    await database.init_database()
    try:
        async with db_conn() as conn:
            await db_installed_apps.insert(
                conn,
                InstalledApp(
                    name=APP_NAME,
                    installation_reason=InstallationReason.CUSTOM,
                    status=status,
                ).model_dump(),
            )
    finally:
        await database.shutdown_database()


@pytest.mark.parametrize("status", [Status.UNINSTALLATION_QUEUED, Status.UNINSTALLING])
async def test_interrupted_uninstall_is_finished_on_next_boot(
    requests_mock, mocker, status
):
    importlib.reload(websocket)
    importlib.reload(app_installation.worker)
    importlib.reload(telemetry)

    async def noop():
        pass

    mocker.patch("shard_core.service.app_installation.login_docker_registries", noop)

    await _seed_interrupted_uninstall(status)

    async with docker_network_portal():
        app = app_factory.create_app()
        async with LifespanManager(app, startup_timeout=20, shutdown_timeout=20):

            async def app_row_is_gone():
                async with db_conn() as conn:
                    assert not await db_installed_apps.contains(conn, APP_NAME)

            await retry_async(app_row_is_gone, timeout=20, frequency=1)
