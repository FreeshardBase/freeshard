import asyncio
import functools
import logging
import subprocess as _sp

log = logging.getLogger(__name__)


@functools.lru_cache(maxsize=1)
def _detect_compose_command() -> tuple[str, ...]:
    try:
        result = _sp.run(
            ["docker", "compose", "version"],
            capture_output=True,
            timeout=5,
        )
        if result.returncode == 0:
            return ("docker", "compose")
    except (FileNotFoundError, _sp.TimeoutExpired):
        pass
    return ("docker-compose",)


def compose_command() -> tuple[str, ...]:
    return _detect_compose_command()


async def subprocess(*args, cwd=None):
    process = await asyncio.create_subprocess_exec(
        *args, cwd=cwd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    log.debug(f'[{" ".join(args)}] started' + ("" if not cwd else f" in {cwd}"))

    try:
        stdout, stderr = await process.communicate()
    except asyncio.CancelledError:
        process.kill()
        await process.wait()
        raise

    if process.returncode != 0:
        raise SubprocessError(
            f"[{process!r} exited with {process.returncode}]\n"
            + f"[stdout]\n{stdout.decode()}"
            + f"[stderr]\n{stderr.decode()}"
        )
    else:
        return stdout.decode()


class SubprocessError(Exception):
    pass
