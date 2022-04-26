import asyncio
import logging
import threading
from asyncio import CancelledError
from contextlib import suppress
from typing import List, Tuple, Callable, Awaitable

log = logging.getLogger(__name__)


class BackgroundTaskHandler:
	def __init__(self, tasks: List[Tuple[Callable[[], Awaitable], float]]):
		"""
		Spawns a single thread executing an asyncio event loop.
		Inside this loop, the tasks that are provided during construction
		are executed repeatedly according to their given delay.

		The *tasks* argument must be a list of tuples, each containing
		a coroutine and a number.
		The coroutine is the task to execute, the number is the duration
		in seconds between each invocation of the coroutine.

		After construction, use the *start()* method to actually
		start the thread and begin executing tasks.

		:param tasks: a list of (coroutine, delay) tuples
		"""
		self._tasks = tasks
		self._stopped_event = threading.Event()
		self._loop: asyncio.AbstractEventLoop = None
		self._gather = None

	def start(self):
		"""
		Start a new event loop in a new thread and begin executing
		the tasks provided during construction
		"""
		_started_event = threading.Event()

		def thread_func():
			wrappers = []
			self._loop = asyncio.new_event_loop()
			asyncio.set_event_loop(self._loop)

			for func, delay in self._tasks:

				async def wrapper(func=func, delay=delay):
					while True:
						try:
							await func()
						except CancelledError:
							raise
						except TaskStopped as e:
							log.debug(f'task {func.__name__} stopped: {e}')
							break
						except Exception as e:
							log.warning(f'background task {func.__name__} raised error: {e}')
							if log.isEnabledFor(logging.DEBUG):
								log.exception(e)

						await asyncio.sleep(delay)

				wrappers.append(wrapper())

			self._gather = asyncio.gather(*wrappers)
			_started_event.set()
			with suppress(CancelledError):
				asyncio.get_event_loop().run_until_complete(self._gather)

			self._stopped_event.set()

		t = threading.Thread(target=thread_func)
		t.daemon = True
		t.start()
		_started_event.wait()

	def stop(self):
		"""
		Arrange for the cancellation of all tasks.
		This function returns immediately but the actual cancelling
		of tasks may take longer.
		Use the returned event to wait until cancellation is complete
		and the event loop and thread are finished.

		:return: an event that is set once cancellation is done
		"""
		self._loop.call_soon_threadsafe(self._gather.cancel)
		return self._stopped_event


class TaskStopped(Exception):
	pass
