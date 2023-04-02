import asyncio
import logging
from contextlib import suppress
from typing import Callable, Awaitable

log = logging.getLogger(__name__)


class Periodic:
	def __init__(self, func: Callable[[], Awaitable], *, delay=None):
		if not delay:
			raise TypeError('delay argument not provided')

		self.func = func
		self.name = func.__name__
		self.delay = delay
		self.is_started = False
		self._task = None

	def start(self):
		if not self.is_started:
			self.is_started = True
			self._task = asyncio.create_task(self._run(), name=self.name)
			log.debug(f'started periodic task {self.name}')

	def stop(self):
		if self.is_started:
			self.is_started = False
			self._task.cancel()
			log.debug(f'stopped periodic task {self.name}')

	async def wait(self):
		with suppress(asyncio.CancelledError):
			await self._task

	async def _run(self):
		while True:
			await self.func()
			await asyncio.sleep(self.delay)
