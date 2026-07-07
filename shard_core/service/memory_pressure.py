import asyncio
import logging
import re
from pathlib import Path

from shard_core.settings import settings
from shard_core.util.subprocess import subprocess, compose_command

log = logging.getLogger(__name__)

# PSI is bind-mounted by the core-version compose file:
# /proc/pressure:/host/pressure:ro (freeshard-controller#246)
PSI_PATH = Path("/host/pressure/memory")
# The host cgroup v2 hierarchy, bind-mounted read-write for memory.reclaim writes.
CGROUP_ROOT = Path("/sys/fs/cgroup")

_PSI_SOME_AVG10_RE = re.compile(r"some.*?avg10=([\d.]+)")


def read_memory_pressure() -> float:
    """Return the `some avg10` value from PSI, 0.0 if unavailable."""
    try:
        text = PSI_PATH.read_text()
    except OSError:
        return 0.0
    match = _PSI_SOME_AVG10_RE.search(text)
    return float(match.group(1)) if match else 0.0


async def reclaim_compose_stack(app_name: str):
    """Write each container's current RSS to its cgroup memory.reclaim,
    proactively paging the frozen processes' anonymous pages out to swap."""
    app_path = Path(settings().path_root) / "core" / "installed_apps" / app_name
    stdout = await subprocess(*compose_command(), "ps", "-q", cwd=app_path)
    container_ids = [line.strip() for line in stdout.splitlines() if line.strip()]
    for container_id in container_ids:
        # The memory.reclaim write blocks while the kernel pages out — run it
        # off the event loop.
        await asyncio.to_thread(_reclaim_container, container_id)


def _reclaim_container(container_id: str):
    cgroup = _find_cgroup(container_id)
    if cgroup is None:
        log.warning(f"no cgroup found for container {container_id}, skipping reclaim")
        return
    current = int((cgroup / "memory.current").read_text().strip())
    if current <= 0:
        return
    try:
        (cgroup / "memory.reclaim").write_text(f"{current}\n")
    except OSError as e:
        # Partial reclaim surfaces as EAGAIN once nothing more can be paged
        # out — the pages that could move are in swap already.
        log.warning(f"memory.reclaim incomplete for container {container_id}: {e}")


def _find_cgroup(container_id: str) -> Path | None:
    candidates = [
        CGROUP_ROOT / "system.slice" / f"docker-{container_id}.scope",  # systemd driver
        CGROUP_ROOT / "docker" / container_id,  # cgroupfs driver
    ]
    return next((path for path in candidates if path.is_dir()), None)
