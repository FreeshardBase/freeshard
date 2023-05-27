import asyncio


async def subprocess(*args, cwd=None):
	up_process = await asyncio.create_subprocess_exec(
		*args,
		cwd=cwd,
		stdout=asyncio.subprocess.PIPE,
		stderr=asyncio.subprocess.PIPE)
	stdout, stderr = await up_process.communicate()

	if up_process.returncode != 0:
		raise SubprocessError(
			f'[{up_process!r} exited with {up_process.returncode}]\n' +
			f'[stdout]\n{stdout.decode()}' +
			f'[stderr]\n{stderr.decode()}'
		)


class SubprocessError(Exception):
	pass
