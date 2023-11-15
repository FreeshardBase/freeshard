import inspect
import time
from contextlib import contextmanager
from pathlib import Path

import gconf
import yappi
from starlette.requests import Request
from starlette.responses import Response


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
def profile(filename: str):
	if gconf.get('log.profiling.enabled', default=False):
		yappi.set_clock_type('wall')
		yappi.clear_stats()
		yappi.start()
		yield
		yappi.stop()
		stats = yappi.get_func_stats(
			filter_callback=lambda x: 'portal_core' in x.module
		)
		path = Path(gconf.get('log.profiling.path')) / f'{filename}.pstat'
		path.parent.mkdir(exist_ok=True, parents=True)
		stats.save(str(path.absolute()), type='pstat')
		yappi.clear_stats()
	else:
		yield


def log_request_and_response(request: Request, response: Response, log):
	entry = [
		'=' * 10 + 'HTTP' + '=' * 10,
		'>' * 10 + ' Request ' + '<' * 10,
		f'{request.method} {request.url}',
		'-' * 10,
		*[f'{k}: {v}' for k, v in request.headers.items()],
		'>' * 10 + ' Response ' + '<' * 10,
		str(response.status_code),
		*[f'{k}: {v}' for k, v in response.headers.items()],
		'=' * 20,
	]
	log.info('\n'.join(entry))
