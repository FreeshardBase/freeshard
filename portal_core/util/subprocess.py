import asyncio
import logging

log = logging.getLogger(__name__)


async def subprocess(*args, cwd=None):
	process = await asyncio.create_subprocess_exec(
		*args,
		cwd=cwd,
		stdout=asyncio.subprocess.PIPE,
		stderr=asyncio.subprocess.PIPE)
	log.debug(f'[{" ".join(args)}] started at {cwd}')
	stdout, stderr = await process.communicate()

	if process.returncode != 0:
		raise SubprocessError(
			f'[{process!r} exited with {process.returncode}]\n' +
			f'[stdout]\n{stdout.decode()}' +
			f'[stderr]\n{stderr.decode()}'
		)
	else:
		return stdout.decode()


class SubprocessError(Exception):
	pass
