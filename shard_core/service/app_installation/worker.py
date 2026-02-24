import asyncio
import logging
import shutil
import zipfile
from contextlib import suppress
from pathlib import Path
from typing import Literal

import gconf
import httpx
from pydantic import BaseModel

from shard_core.database.connection import db_conn
from shard_core.database import installed_apps as installed_apps_db
from shard_core.data_model.app_meta import Status
from shard_core.service.app_tools import (
    get_installed_apps_path,
    docker_create_app_containers,
    docker_stop_app,
    docker_shutdown_app,
)
from shard_core.util import signals
from .exceptions import AppDoesNotExist
from .util import (
    update_app_status,
    render_docker_compose_template,
    write_traefik_dyn_config,
    get_app_from_db,
    assert_app_status,
)

log = logging.getLogger(__name__)


class InstallationTask(BaseModel):
    app_name: str
    task_type: Literal[
        "install from store", "install from zip", "uninstall", "reinstall"
    ]

    def __str__(self):
        return f'"{self.task_type}" task for {self.app_name}'


class InstallationWorker:
    def __init__(self):
        self._task_queue: asyncio.Queue[InstallationTask] = asyncio.Queue()
        self.is_started = False
        self.current_task = None
        self._task = None

    def enqueue(self, task: InstallationTask):
        self._task_queue.put_nowait(task)
        log.debug(f"enqueued {task}, queue size: {self._task_queue.qsize()}")

    def start(self):
        if not self.is_started:
            self.is_started = True
            self._task = asyncio.create_task(self._run(), name="InstallationWorker")
            log.debug("started InstallationWorker")

    def stop(self):
        if self.is_started:
            self.is_started = False
            self._task.cancel()
            log.debug("stopped InstallationWorker")

    async def wait(self):
        with suppress(asyncio.CancelledError):
            await self._task

    async def _run(self):
        while True:
            self.current_task = await self._task_queue.get()
            log.info(f"processing {self.current_task}")
            try:
                if self.current_task.task_type == "install from store":
                    await _install_app_from_store(self.current_task.app_name)
                elif self.current_task.task_type == "install from zip":
                    await _install_app_from_existing_zip(self.current_task.app_name)
                elif self.current_task.task_type == "uninstall":
                    await _uninstall_app(self.current_task.app_name)
                elif self.current_task.task_type == "reinstall":
                    await _reinstall_app(self.current_task.app_name)
                log.info(f"finished {self.current_task}")
            except Exception as e:
                log.error(f"Error during {self.current_task}: {e}")
            finally:
                self._task_queue.task_done()
                self.current_task = None


installation_worker = InstallationWorker()


async def _install_app_from_store(app_name: str):
    installed_app = await get_app_from_db(app_name)
    assert_app_status(installed_app, Status.INSTALLATION_QUEUED)
    await update_app_status(installed_app.name, Status.INSTALLING)
    try:
        zip_file = await _download_app_zip(installed_app.name)
        await _install_app_from_zip(installed_app, zip_file)
        await update_app_status(installed_app.name, Status.STOPPED)
    except Exception as e:
        await update_app_status(installed_app.name, Status.ERROR, message=repr(e))
        signals.on_app_install_error.send((e, app_name))


async def _install_app_from_existing_zip(app_name: str):
    installed_app = await get_app_from_db(app_name)
    assert_app_status(installed_app, Status.INSTALLATION_QUEUED)
    await update_app_status(installed_app.name, Status.INSTALLING)
    try:
        zip_file = (
            get_installed_apps_path() / installed_app.name / f"{installed_app.name}.zip"
        )
        await _install_app_from_zip(installed_app, zip_file)
        await update_app_status(installed_app.name, Status.STOPPED)
    except Exception as e:
        await update_app_status(installed_app.name, Status.ERROR, message=repr(e))
        signals.on_app_install_error.send((e, app_name))


async def _uninstall_app(app_name: str):
    try:
        await update_app_status(app_name, Status.UNINSTALLING)
    except KeyError:
        log.warning(f"during uninstallation of {app_name}: app not found in database")

    try:
        await docker_stop_app(app_name)
        await docker_shutdown_app(app_name)
    except Exception as e:
        log.error(f"Error while shutting down app {app_name}: {e:!r}")

    log.debug(f"deleting app data for {app_name}")
    shutil.rmtree(Path(get_installed_apps_path() / app_name), ignore_errors=True)
    log.debug(f"removing app {app_name} from database")
    async with db_conn() as conn:
        await installed_apps_db.remove(conn, app_name)
    await write_traefik_dyn_config()
    signals.on_apps_update.send()
    log.info(f"uninstalled {app_name}")


async def _reinstall_app(app_name: str):
    installed_app = await get_app_from_db(app_name)
    assert_app_status(installed_app, Status.REINSTALLATION_QUEUED)
    await update_app_status(installed_app.name, Status.REINSTALLING)

    try:
        await docker_stop_app(app_name, set_status=False)
        await docker_shutdown_app(app_name, set_status=False)
    except Exception as e:
        log.error(f"Error while shutting down app {app_name}: {e:!r}")

    log.debug(f"deleting app data for {app_name}")
    shutil.rmtree(Path(get_installed_apps_path() / app_name), ignore_errors=True)

    try:
        zip_file = await _download_app_zip(installed_app.name)
        await _install_app_from_zip(installed_app, zip_file)
        await update_app_status(installed_app.name, Status.STOPPED)
    except Exception as e:
        await update_app_status(installed_app.name, Status.ERROR, message=repr(e))
        signals.on_app_install_error.send((e, app_name))


async def _install_app_from_zip(installed_app, zip_file):
    with zipfile.ZipFile(zip_file, "r") as zip_ref:
        zip_ref.extractall(zip_file.parent)
    signals.on_apps_update.send()
    zip_file.unlink()

    await render_docker_compose_template(installed_app)
    await docker_create_app_containers(installed_app.name)
    await write_traefik_dyn_config()


async def _download_app_zip(name: str) -> Path:
    app_store = gconf.get("apps.app_store")
    url = f'{app_store["base_url"]}/{app_store["container_name"]}/master/all_apps/{name}/{name}.zip'
    async with httpx.AsyncClient() as client:
        response = await client.get(url)
        if response.status_code != 200:
            raise AppDoesNotExist(url)
        zip_file = get_installed_apps_path() / name / f"{name}.zip"
        zip_file.parent.mkdir(parents=True, exist_ok=True)
        with open(zip_file, "wb") as f:
            f.write(response.content)
    log.debug(f"downloaded {name} to {zip_file}")
    return zip_file
