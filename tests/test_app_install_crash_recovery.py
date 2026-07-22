import importlib

import pytest
from asgi_lifespan import LifespanManager

from shard_core import app_factory
from shard_core.data_model.app_meta import InstallationReason, InstalledApp, Status
from shard_core.database import database
from shard_core.database import installed_apps as db_installed_apps
from shard_core.database.connection import db_conn
from shard_core.service import app_installation, telemetry, websocket
from shard_core.service.app_installation import worker
from shard_core.service.app_tools import get_installed_apps_path
from tests.util import docker_network_portal, retry_async

pytest_plugins = ("pytest_asyncio",)
pytestmark = pytest.mark.asyncio

config_override = {"apps": {"initial_apps": []}}

APP_NAME = "mock_app"


async def _seed_app(status: Status, reason: InstallationReason):
    async with db_conn() as conn:
        await db_installed_apps.insert(
            conn,
            InstalledApp(
                name=APP_NAME,
                installation_reason=reason,
                status=status,
            ).model_dump(),
        )


async def _status(app_name: str) -> str:
    async with db_conn() as conn:
        record = await db_installed_apps.get_by_name(conn, app_name)
    return record["status"]


def _place_zip(app_name: str):
    zip_file = get_installed_apps_path() / app_name / f"{app_name}.zip"
    zip_file.parent.mkdir(parents=True, exist_ok=True)
    zip_file.write_bytes(b"not a real zip, only its presence matters here")
    return zip_file


# --- decision matrix (db-tier, worker not started) ------------------------


@pytest.mark.parametrize("status", [Status.INSTALLATION_QUEUED, Status.INSTALLING])
async def test_custom_install_without_zip_is_marked_error(db, mocker, status):
    enqueue = mocker.patch.object(worker.installation_worker, "enqueue")
    await _seed_app(status, InstallationReason.CUSTOM)

    await app_installation.reconcile_interrupted_installs()

    assert await _status(APP_NAME) == Status.ERROR
    enqueue.assert_not_called()


@pytest.mark.parametrize("status", [Status.INSTALLATION_QUEUED, Status.INSTALLING])
async def test_custom_install_with_zip_is_requeued_from_zip(db, mocker, status):
    enqueue = mocker.patch.object(worker.installation_worker, "enqueue")
    await _seed_app(status, InstallationReason.CUSTOM)
    zip_file = _place_zip(APP_NAME)
    try:
        await app_installation.reconcile_interrupted_installs()
    finally:
        zip_file.unlink(missing_ok=True)

    assert await _status(APP_NAME) == Status.INSTALLATION_QUEUED
    enqueue.assert_called_once()
    assert enqueue.call_args.args[0].task_type == "install from zip"


@pytest.mark.parametrize("status", [Status.INSTALLATION_QUEUED, Status.INSTALLING])
@pytest.mark.parametrize(
    "reason", [InstallationReason.STORE, InstallationReason.CONFIG]
)
async def test_store_install_without_zip_is_requeued_from_store(
    db, mocker, status, reason
):
    enqueue = mocker.patch.object(worker.installation_worker, "enqueue")
    await _seed_app(status, reason)

    await app_installation.reconcile_interrupted_installs()

    assert await _status(APP_NAME) == Status.INSTALLATION_QUEUED
    enqueue.assert_called_once()
    assert enqueue.call_args.args[0].task_type == "install from store"


@pytest.mark.parametrize("status", [Status.REINSTALLATION_QUEUED, Status.REINSTALLING])
async def test_interrupted_reinstall_is_requeued(db, mocker, status):
    enqueue = mocker.patch.object(worker.installation_worker, "enqueue")
    await _seed_app(status, InstallationReason.STORE)

    await app_installation.reconcile_interrupted_installs()

    assert await _status(APP_NAME) == Status.REINSTALLATION_QUEUED
    enqueue.assert_called_once()
    assert enqueue.call_args.args[0].task_type == "reinstall"


@pytest.mark.parametrize("status", [Status.STOPPED, Status.RUNNING, Status.ERROR])
async def test_settled_apps_are_left_untouched(db, mocker, status):
    enqueue = mocker.patch.object(worker.installation_worker, "enqueue")
    await _seed_app(status, InstallationReason.STORE)

    await app_installation.reconcile_interrupted_installs()

    assert await _status(APP_NAME) == status
    enqueue.assert_not_called()


# --- boot loop protection (full lifespan) ---------------------------------


async def _seed_interrupted_install(status: Status):
    """Leave behind what a stop mid-install of a custom app leaves: a row in an
    installing status, no zip and no metadata on disk, nothing in the queue."""
    await database.init_database()
    try:
        await _seed_app(status, InstallationReason.CUSTOM)
    finally:
        await database.shutdown_database()


@pytest.mark.parametrize("status", [Status.INSTALLATION_QUEUED, Status.INSTALLING])
async def test_interrupted_install_with_missing_files_boots_and_errors(
    requests_mock, mocker, status
):
    importlib.reload(websocket)
    importlib.reload(app_installation.worker)
    importlib.reload(telemetry)

    async def noop():
        pass

    mocker.patch("shard_core.service.app_installation.login_docker_registries", noop)

    await _seed_interrupted_install(status)

    async with docker_network_portal():
        app = app_factory.create_app()
        async with LifespanManager(app, startup_timeout=20, shutdown_timeout=20):

            async def app_row_is_error():
                assert await _status(APP_NAME) == Status.ERROR

            await retry_async(app_row_is_error, timeout=20, frequency=1)
