import inspect
import time
from contextlib import contextmanager

import gconf
import yappi


def throttle(min_duration: float):
	def decorator_throttle(func):
		last_call = None

		if inspect.iscoroutinefunction(func):
			async def wrapper_throttle(*args, **kwargs):
				nonlocal last_call
				if last_call is None or last_call + min_duration < time.time():
					last_call = time.time()
					return await func(*args, **kwargs)
		else:
			def wrapper_throttle(*args, **kwargs):
				nonlocal last_call
				if last_call is None or last_call + min_duration < time.time():
					last_call = time.time()
					return func(*args, **kwargs)

		return wrapper_throttle

	return decorator_throttle


@contextmanager
def profile():
	if gconf.get('log.profiling', default=False):
		yappi.set_clock_type('wall')
		yappi.clear_stats()
		yappi.start()
		yield
		yappi.stop()
		stats = yappi.get_func_stats(
			filter_callback=lambda x: 'portal_core' in x.module
		)
		stats.save('profile.pstat', type='pstat')
		yappi.clear_stats()
	else:
		yield
