import asyncio
import functools
import logging
import re
import subprocess as _sp
from pathlib import Path

log = logging.getLogger(__name__)

COMPOSE_FILE_NAME = "docker-compose.yml"

# The core stack's compose project — an app command must never resolve to it.
CORE_PROJECT_NAME = "core"

_PROJECT_NAME_INVALID_CHARS_RE = re.compile(r"[^a-z0-9_-]")


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


def normalize_project_name(name: str) -> str:
    """Mirror compose's own directory-name -> project-name normalization:
    lowercase, drop everything outside [a-z0-9_-], strip leading _ and -."""
    return _PROJECT_NAME_INVALID_CHARS_RE.sub("", name.lower()).lstrip("_-")


def app_compose_command(app_dir: Path) -> tuple[str, ...]:
    """Build a compose command pinned to one app's compose file and project.

    Without -f/-p, compose derives both from the working directory and walks up
    the tree when no compose file is there — from an app dir that lands on the
    core stack, so an app `stop`/`down` takes the whole shard offline.
    """
    compose_file = app_dir / COMPOSE_FILE_NAME
    if not compose_file.is_file():
        raise ComposeFileNotFound(compose_file)
    project_name = normalize_project_name(app_dir.name)
    if not project_name:
        raise ComposeProjectNotAllowed(f"app dir {app_dir} has no valid project name")
    if project_name == CORE_PROJECT_NAME:
        raise ComposeProjectNotAllowed(
            f"app dir {app_dir} resolves to the core compose project"
        )
    return (
        *compose_command(),
        "-f",
        str(compose_file),
        "-p",
        project_name,
        "--project-directory",
        str(app_dir),
    )


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


class ComposeFileNotFound(Exception):
    pass


class ComposeProjectNotAllowed(Exception):
    pass
