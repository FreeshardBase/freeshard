import asyncio
import logging
import random
import time
from abc import ABC, abstractmethod
from contextlib import suppress
from typing import Callable, Awaitable

from croniter import croniter, CroniterBadCronError

log = logging.getLogger(__name__)


class BackgroundTask(ABC):
	@abstractmethod
	def start(self):
		...

	@abstractmethod
	def stop(self):
		...

	@abstractmethod
	async def wait(self):
		...


class PeriodicTask(BackgroundTask):
	def __init__(self, func: Callable[[], Awaitable], delay):
		self.func = func
		self.name = func.__name__
		self.delay = delay
		self.is_started = False
		self._task = None

	def start(self):
		if not self.is_started:
			self.is_started = True
			self._task = asyncio.create_task(self._run_delay(), name=self.name)
			log.debug(f'started periodic task {self.name} on delay')

	def stop(self):
		if self.is_started:
			self.is_started = False
			self._task.cancel()
			log.debug(f'stopped periodic task {self.name}')

	async def wait(self):
		with suppress(asyncio.CancelledError):
			await self._task

	async def _run_delay(self):
		while True:
			try:
				await self.func()
			except Exception as e:
				log.error(f'error in periodic task {self.name}: {type(e).__name__}({e})')
			await asyncio.sleep(self.delay)


class CronTask(BackgroundTask):
	def __init__(self, func: Callable[[], Awaitable], cron: str, max_random_delay=None):
		try:
			croniter(cron)
		except CroniterBadCronError as e:
			raise TypeError from e

		self.func = func
		self.name = func.__name__
		self.cron = cron
		self.max_random_delay = max_random_delay
		self.is_started = False
		self._task = None

	def start(self):
		if not self.is_started:
			self.is_started = True
			self._task = asyncio.create_task(self._run_cron(), name=self.name)
			log.debug(f'started cron task {self.name}')

	def stop(self):
		if self.is_started:
			self.is_started = False
			self._task.cancel()
			log.debug(f'stopped cron task {self.name}')

	async def wait(self):
		with suppress(asyncio.CancelledError):
			await self._task

	async def _run_cron(self):
		while True:
			next_exec: float = croniter(self.cron).get_next()
			if self.max_random_delay:
				next_exec += random.uniform(0, self.max_random_delay)
			delta = next_exec - time.time()
			log.debug(f'next execution of cron task {self.name} in {delta:.2f} seconds')
			await asyncio.sleep(delta)
			await self.func()
