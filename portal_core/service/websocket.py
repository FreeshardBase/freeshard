import asyncio
import logging
from asyncio import Task
from contextlib import suppress
from typing import Dict, List

from pydantic import BaseModel
from starlette.websockets import WebSocket

from portal_core.database.database import terminals_table, installed_apps_table
from portal_core.model.app_meta import InstalledApp
from portal_core.model.terminal import Terminal
from portal_core.service.app_tools import enrich_installed_app_with_meta
from portal_core.util import signals
from portal_core.util.async_util import BackgroundTask

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
				self._send_messages(), name='WSWorker messages')
			self._heartbeat_task = asyncio.create_task(
				self._send_heartbeats(), name='WSWorker heartbeat')
			log.debug('Started WSWorker task')

	def stop(self):
		if self.is_started:
			self.is_started = False
			self._message_task.cancel()
			self._heartbeat_task.cancel()
			log.debug('Stopped WSWorker task')

	async def wait(self):
		with suppress(asyncio.CancelledError):
			await self._message_task
			await self._heartbeat_task

	async def _send_messages(self):
		while True:
			message = await self.outgoing_messages.get()
			log.debug(f'sending {message.message_type} message')
			try:
				await asyncio.gather(*[s.send_text(message.json()) for s in self.active_sockets])
			except Exception as e:
				log.error(f'Error during websocket sending: {e}')

	async def _send_heartbeats(self):
		while True:
			await self.broadcast_message('heartbeat')
			await asyncio.sleep(30)

	async def connect(self, websocket: WebSocket):
		await websocket.accept()
		self.active_sockets.append(websocket)

	def disconnect(self, websocket: WebSocket):
		self.active_sockets.remove(websocket)

	async def send_personal_message(self, message: str, websocket: WebSocket):
		await websocket.send_text(message)

	async def broadcast_message(self, message_type: str, message: Dict | List | None = None):
		log.debug(f'enqueuing {message_type} message for sending, queue size: {self.outgoing_messages.qsize()}')
		await self.outgoing_messages.put(Message(
			message_type=message_type,
			message=message or {},
		))


ws_worker = WSWorker()


@signals.on_terminals_update.connect
async def send_terminals_update(_):
	with terminals_table() as terminals:  # type: Table
		all_terminals = terminals.all()
	await ws_worker.broadcast_message('terminals_update', all_terminals)


@signals.on_terminal_add.connect
async def send_terminal_add(terminal: Terminal):
	await ws_worker.broadcast_message('terminal_add', terminal.dict())


@signals.on_apps_update.connect
async def send_apps_update(_):
	with installed_apps_table() as installed_apps:
		all_apps = installed_apps.all()
	enriched_apps = [enrich_installed_app_with_meta(InstalledApp.parse_obj(app)) for app in all_apps]
	await ws_worker.broadcast_message('apps_update', enriched_apps)


@signals.on_app_install_error.connect
async def send_app_install_error(e: Exception, name: str):
	await ws_worker.broadcast_message('app_install_error', {'name': name, 'error': f'{type(e).__name__} {e}'})
