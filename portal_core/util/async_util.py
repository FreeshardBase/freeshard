import asyncio
import logging
import time
from contextlib import suppress
from datetime import datetime, timedelta
from typing import Callable, Awaitable
from croniter import croniter, CroniterBadCronError

log = logging.getLogger(__name__)


class Periodic:
	def __init__(self, func: Callable[[], Awaitable], *, delay=None, cron=None):
		if not any([delay, cron]):
			raise TypeError('one of delay, cron must be provided')
		if delay and cron:
			raise TypeError('only one of delay, cron must be provided')
		if cron:
			try:
				croniter(cron)
			except CroniterBadCronError as e:
				raise TypeError from e

		self.func = func
		self.name = func.__name__
		self.delay = delay
		self.cron = cron
		self.is_started = False
		self._task = None

	def start(self):
		if not self.is_started:
			self.is_started = True
			if self.delay:
				self._task = asyncio.create_task(self._run_delay(), name=self.name)
				log.debug(f'started periodic task {self.name} on delay')
			if self.cron:
				self._task = asyncio.create_task(self._run_cron(), name=self.name)
				log.debug(f'started periodic task {self.name} on cron')

	def stop(self):
		if self.is_started:
			self.is_started = False
			self._task.cancel()
			log.debug(f'stopped periodic task {self.name}')

	async def wait(self):
		with suppress(asyncio.CancelledError):
			await self._task

	async def _run_cron(self):
		while True:
			next_exec: float = croniter(self.cron).get_next()
			delta = next_exec - time.time()
			await asyncio.sleep(delta)
			await self.func()

	async def _run_delay(self):
		while True:
			await self.func()
			await asyncio.sleep(self.delay)
