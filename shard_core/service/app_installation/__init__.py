import logging
import shutil
from pathlib import Path

from shard_core.database import database
from shard_core.database.connection import db_conn
from shard_core.database import installed_apps as db_installed_apps
from shard_core.data_model.app_meta import InstallationReason, InstalledApp, Status
from shard_core.util import signals
from shard_core.settings import settings
from shard_core.service.app_tools import get_installed_apps_path
from shard_core.util.subprocess import subprocess, SubprocessError
from . import util, worker
from .exceptions import AppAlreadyInstalled, AppDoesNotExist, AppNotInstalled

log = logging.getLogger(__name__)

STORE_KEY_INITIAL_APPS_INSTALLED = "initial_apps_installed"


async def install_app_from_store(
    name: str,
    installation_reason: InstallationReason = InstallationReason.STORE,
):
    if not await util.app_exists_in_store(name):
        raise AppDoesNotExist(name)

    if await util.app_exists_in_db(name):
        raise AppAlreadyInstalled(name)

    async with db_conn() as conn:
        installed_app = InstalledApp(
            name=name,
            installation_reason=installation_reason,
            status=Status.INSTALLATION_QUEUED,
        )
        await db_installed_apps.insert(conn, installed_app.model_dump())

    installation_task = worker.InstallationTask(
        app_name=name,
        task_type="install from store",
    )
    worker.installation_worker.enqueue(installation_task)
    await signals.on_apps_update.send_async()
    log.info(f"created {installation_task}")


async def install_app_from_uploaded_zip(
    name: str,
    zip_file: Path,
    installation_reason: InstallationReason = InstallationReason.CUSTOM,
):
    if await util.app_exists_in_db(name):
        raise AppAlreadyInstalled(name)

    target_zip = get_installed_apps_path() / name / f"{name}.zip"
    target_zip.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(zip_file, target_zip)

    async with db_conn() as conn:
        installed_app = InstalledApp(
            name=name,
            installation_reason=installation_reason,
            status=Status.INSTALLATION_QUEUED,
        )
        await db_installed_apps.insert(conn, installed_app.model_dump())

    installation_task = worker.InstallationTask(
        app_name=name,
        task_type="install from zip",
    )
    worker.installation_worker.enqueue(installation_task)
    await signals.on_apps_update.send_async()
    log.info(f"created {installation_task}")


async def uninstall_app(name: str):
    if not await util.app_exists_in_db(name):
        raise AppNotInstalled(name)

    await util.update_app_status(name, Status.UNINSTALLATION_QUEUED)

    uninstallation_task = worker.InstallationTask(
        app_name=name,
        task_type="uninstall",
    )
    worker.installation_worker.enqueue(uninstallation_task)

    await signals.on_apps_update.send_async()
    log.info(f"created {uninstallation_task}")


async def reinstall_app(name: str):
    if not await util.app_exists_in_store(name):
        raise AppDoesNotExist(name)

    if not await util.app_exists_in_db(name):
        raise AppNotInstalled(name)

    await util.update_app_status(name, Status.REINSTALLATION_QUEUED)

    reinstallation_task = worker.InstallationTask(
        app_name=name,
        task_type="reinstall",
    )
    worker.installation_worker.enqueue(reinstallation_task)

    log.info(f"created {reinstallation_task}")


async def reconcile_interrupted_uninstalls():
    """Re-enqueue uninstalls that a previous process did not finish.

    The task queue only lives in memory, so a stop between the status flip and the
    row delete strands the row in UNINSTALLING with nothing left to resume it.
    Enqueue only — the worker is started later in the lifespan.
    """
    async with db_conn() as conn:
        all_apps = await db_installed_apps.get_all(conn)

    for app in all_apps:
        if app["status"] not in (Status.UNINSTALLATION_QUEUED, Status.UNINSTALLING):
            continue
        worker.installation_worker.enqueue(
            worker.InstallationTask(app_name=app["name"], task_type="uninstall")
        )
        log.info(f"resuming interrupted uninstallation of {app['name']}")


async def reconcile_interrupted_installs():
    """Resume or fail installs and reinstalls a previous process left in flight.

    Like uninstalls, the task queue lives only in memory: a stop while a row is
    in an installing status strands it with nothing left to resume it. Re-enqueue
    the work when its source still exists, otherwise mark the row ERROR so it
    stops looking half-installed and no longer blocks a fresh install. Enqueue
    only — the worker starts later in the lifespan.
    """
    async with db_conn() as conn:
        all_apps = await db_installed_apps.get_all(conn)

    for record in all_apps:
        app = InstalledApp.model_validate(record)
        if app.status in (Status.INSTALLATION_QUEUED, Status.INSTALLING):
            await _resume_interrupted_install(app)
        elif app.status in (Status.REINSTALLATION_QUEUED, Status.REINSTALLING):
            await _resume_interrupted_reinstall(app)


async def _resume_interrupted_install(app: InstalledApp):
    zip_file = get_installed_apps_path() / app.name / f"{app.name}.zip"
    if zip_file.exists():
        task_type = "install from zip"
    elif app.installation_reason in (
        InstallationReason.STORE,
        InstallationReason.CONFIG,
    ):
        task_type = "install from store"
    else:
        await util.update_app_status(
            app.name,
            Status.ERROR,
            message="installation interrupted by a restart and its source is gone",
        )
        log.warning(
            f"cannot resume interrupted installation of {app.name}, marking ERROR"
        )
        return

    await util.update_app_status(app.name, Status.INSTALLATION_QUEUED)
    worker.installation_worker.enqueue(
        worker.InstallationTask(app_name=app.name, task_type=task_type)
    )
    log.info(f"resuming interrupted installation of {app.name}")


async def _resume_interrupted_reinstall(app: InstalledApp):
    # a reinstall re-downloads from the store; the worker marks the row ERROR if
    # the app is no longer there, so re-enqueueing is always safe.
    await util.update_app_status(app.name, Status.REINSTALLATION_QUEUED)
    worker.installation_worker.enqueue(
        worker.InstallationTask(app_name=app.name, task_type="reinstall")
    )
    log.info(f"resuming interrupted reinstallation of {app.name}")


async def refresh_init_apps():
    try:
        await database.get_value(STORE_KEY_INITIAL_APPS_INSTALLED)
        log.debug("initial apps already installed on first startup, skipping")
        return
    except KeyError:
        pass  # first startup — flag not yet set

    configured_init_apps = set(settings().apps.initial_apps)
    async with db_conn() as conn:
        all_apps = await db_installed_apps.get_all(conn)
    installed_apps = {app["name"] for app in all_apps}

    for app_name in configured_init_apps - installed_apps:
        log.info(f"installing initial app {app_name}")
        await install_app_from_store(app_name, InstallationReason.CONFIG)

    await database.set_value(STORE_KEY_INITIAL_APPS_INSTALLED, True)
    log.debug("refreshed initial apps")


async def login_docker_registries():
    registries = settings().apps.registries
    for r in registries:
        try:
            await subprocess(
                "docker", "login", "-u", r.username, "-p", r.password, r.uri
            )
        except (SubprocessError, OSError) as e:
            log.error(f"could not log in to registry {r.uri}: {e}")
        else:
            log.debug(f"logged in to registry {r.uri}")
