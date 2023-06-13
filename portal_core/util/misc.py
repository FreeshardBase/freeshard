import functools
import time


def throttle(min_duration: float):
	def decorator_throttle(func):
		last_call = None

		@functools.wraps(func)
		def wrapper_throttle():
			nonlocal last_call
			if last_call is None or last_call + min_duration < time.time():
				last_call = time.time()
				return func()

		return wrapper_throttle

	return decorator_throttle
