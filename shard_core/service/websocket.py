import asyncio
import logging
from asyncio import Task
from contextlib import suppress
from typing import Dict, List, Tuple

from pydantic import BaseModel
from starlette.websockets import WebSocket

from shard_core.db import installed_apps, terminals
from shard_core.db.db_connection import db_conn
from shard_core.data_model.app_meta import InstalledApp
from shard_core.data_model.terminal import Terminal
from shard_core.service.app_tools import enrich_installed_app_with_meta
from shard_core.service.disk import DiskUsage
from shard_core.util import signals
from shard_core.util.async_util import BackgroundTask
from shard_core.util.misc import format_error

log = logging.getLogger(__name__)


class Message(BaseModel):
    message_type: str
    message: Dict | List


class WSWorker(BackgroundTask):
    def __init__(self):
        self.active_sockets: list[WebSocket] = []
        self.outgoing_messages: asyncio.Queue[Message] = asyncio.Queue(maxsize=0)
        self.is_started = False
        self._message_task: Task | None = None
        self._heartbeat_task: Task | None = None

    def start(self):
        if not self.is_started:
            self.is_started = True
            self._message_task = asyncio.create_task(
                self._send_messages(), name="WSWorker messages"
            )
            self._heartbeat_task = asyncio.create_task(
                self._send_heartbeats(), name="WSWorker heartbeat"
            )
            log.debug("Started WSWorker task")

    def stop(self):
        if self.is_started:
            self.is_started = False
            self._message_task.cancel()
            self._heartbeat_task.cancel()
            log.debug("Stopped WSWorker task")

    async def wait(self):
        with suppress(asyncio.CancelledError):
            await self._message_task
            await self._heartbeat_task

    async def _send_messages(self):
        while True:
            message = await self.outgoing_messages.get()
            log.debug(f"sending {message.message_type} message")
            try:
                await asyncio.gather(
                    *[s.send_text(message.json()) for s in self.active_sockets]
                )
            except Exception as e:
                log.error(f"Error during websocket sending: {e}")

    async def _send_heartbeats(self):
        while True:
            await self.broadcast_message("heartbeat")
            await asyncio.sleep(30)

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_sockets.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_sockets.remove(websocket)

    async def send_personal_message(self, message: str, websocket: WebSocket):
        await websocket.send_text(message)

    def broadcast_message(self, message_type: str, message: Dict | List | None = None):
        log.debug(
            f"enqueuing {message_type} message for sending, queue size: {self.outgoing_messages.qsize()}"
        )
        try:
            self.outgoing_messages.put_nowait(
                Message(
                    message_type=message_type,
                    message=message or {},
                )
            )
        except asyncio.QueueFull:
            log.error("Websocket message queue is full, dropping message")


ws_worker = WSWorker()


@signals.on_backup_update.connect
def send_backup_update(e: Exception | None = None):
    ws_worker.broadcast_message(
        "backup_update", {"error": format_error(e)} if e else None
    )


@signals.on_disk_usage_update.connect
def send_disk_usage_update(disk_usage: DiskUsage):
    ws_worker.broadcast_message("disk_usage_update", disk_usage.dict())


@signals.on_terminals_update.connect
async def send_terminals_update(_):
    async with db_conn() as conn:
        all_terminals = await terminals.get_all(conn)
    ws_worker.broadcast_message("terminals_update", [t.dict() for t in all_terminals])


@signals.on_terminal_add.connect
async def send_terminal_add(terminal: Terminal):
    ws_worker.broadcast_message("terminal_add", terminal.dict())


@signals.on_apps_update.connect
async def send_apps_update(_):
    async with db_conn() as conn:
        all_apps = await installed_apps.get_all(conn)
    enriched_apps = [
        enrich_installed_app_with_meta(app) for app in all_apps
    ]
    ws_worker.broadcast_message("apps_update", enriched_apps)


@signals.on_app_install_error.connect
def send_app_install_error(args: Tuple[Exception, str]):
    e, name = args
    ws_worker.broadcast_message(
        "app_install_error", {"name": name, "error": format_error(e)}
    )
