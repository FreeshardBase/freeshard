"""Per-app and shard-level CPU + memory metrics for the resource monitor.

A single background sampler (`update_stats`, run by a PeriodicTask) refreshes an
in-memory snapshot every few seconds, mirroring the `disk.py` pattern. The protected
`GET /protected/stats` (shard rollup) and `GET /protected/apps/{name}/stats` (per app)
endpoints serve the latest snapshot without doing any docker/cgroup work per request.

Memory uses cgroup v2 `memory.current` — the same metric `memory.reclaim` operates on —
which counts resident memory only; pages swapped out of a paused app move to
`memory.swap.current` and are reported separately as `memory_swap_bytes`. CPU is the
`cpu.stat` `usage_usec` delta between two samples over the elapsed wall-clock interval.
"""

import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel

from shard_core.database import installed_apps as db_installed_apps
from shard_core.database.connection import db_conn
from shard_core.service.memory_pressure import find_cgroup
from shard_core.util.subprocess import (
    SubprocessError,
    normalize_project_name,
    subprocess,
)

log = logging.getLogger(__name__)

PROC_STAT_PATH = Path("/proc/stat")
MEMINFO_PATH = Path("/proc/meminfo")
COMPOSE_PROJECT_LABEL = "com.docker.compose.project"

_CPU_USAGE_USEC_RE = re.compile(r"usage_usec (\d+)")


class AppStats(BaseModel):
    name: str
    status: str
    memory_bytes: int
    memory_swap_bytes: int
    cpu_pct: float


class ShardStats(BaseModel):
    cpu_pct: float
    memory_bytes: int
    memory_limit_bytes: int
    memory_swap_bytes: int


# Latest snapshot, served by the endpoints. Updated wholesale by `update_stats` so a
# request never sees a half-written sample.
current_shard_stats = ShardStats(
    cpu_pct=0.0, memory_bytes=0, memory_limit_bytes=0, memory_swap_bytes=0
)
current_app_stats: dict[str, AppStats] = {}

# Previous-sample bookkeeping for CPU deltas. CPU is a rate, so the first sample after
# startup has nothing to diff against and reports 0.0.
_prev_time: float | None = None
_prev_app_cpu_usec: dict[str, int] = {}
_prev_cpu_total: int | None = None
_prev_cpu_idle: int | None = None


@dataclass
class _MemInfo:
    total_bytes: int
    available_bytes: int
    swap_total_bytes: int
    swap_free_bytes: int

    @property
    def used_bytes(self) -> int:
        return max(self.total_bytes - self.available_bytes, 0)

    @property
    def swap_used_bytes(self) -> int:
        return max(self.swap_total_bytes - self.swap_free_bytes, 0)


def _read_int_file(path: Path) -> int:
    """Read a single-integer cgroup file; 0 if absent/unreadable (e.g. `max`)."""
    try:
        return int(path.read_text().strip())
    except (OSError, ValueError):
        return 0


def _read_cgroup_memory(cgroup: Path) -> tuple[int, int]:
    """Return (resident bytes, swapped bytes) for one container's cgroup."""
    return (
        _read_int_file(cgroup / "memory.current"),
        _read_int_file(cgroup / "memory.swap.current"),
    )


def _read_cgroup_cpu_usec(cgroup: Path) -> int:
    """Cumulative CPU time in microseconds from cgroup v2 `cpu.stat`, 0 if unreadable."""
    try:
        text = (cgroup / "cpu.stat").read_text()
    except OSError:
        return 0
    match = _CPU_USAGE_USEC_RE.search(text)
    return int(match.group(1)) if match else 0


def _cpu_pct(delta_usec: int, elapsed_s: float) -> float:
    """CPU busy percentage over an interval. Can exceed 100% on multiple cores."""
    if elapsed_s <= 0 or delta_usec < 0:
        return 0.0
    return round(delta_usec / (elapsed_s * 1_000_000) * 100, 2)


def _cpu_pct_from_jiffies(total_delta: int, idle_delta: int) -> float:
    """Host CPU busy percentage from /proc/stat jiffie deltas."""
    if total_delta <= 0:
        return 0.0
    return round(max(total_delta - idle_delta, 0) / total_delta * 100, 2)


def _parse_proc_stat(text: str) -> tuple[int, int] | None:
    """Return (total jiffies, idle jiffies) from the aggregate `cpu` line."""
    for line in text.splitlines():
        if line.startswith("cpu "):
            fields = [int(v) for v in line.split()[1:]]
            if len(fields) < 5:
                return None
            # idle = idle + iowait (fields[3], fields[4]).
            total = sum(fields)
            idle = fields[3] + fields[4]
            return total, idle
    return None


def _parse_meminfo(text: str) -> _MemInfo:
    def _kib(key: str) -> int | None:
        match = re.search(rf"^{key}:\s+(\d+) kB", text, re.MULTILINE)
        return int(match.group(1)) if match else None

    total = _kib("MemTotal") or 0
    # MemAvailable is the kernel's own estimate of reclaimable memory; fall back to
    # MemFree on kernels old enough to lack it.
    available = _kib("MemAvailable")
    if available is None:
        available = _kib("MemFree") or 0
    swap_total = _kib("SwapTotal") or 0
    swap_free = _kib("SwapFree") or 0
    return _MemInfo(
        total_bytes=total * 1024,
        available_bytes=available * 1024,
        swap_total_bytes=swap_total * 1024,
        swap_free_bytes=swap_free * 1024,
    )


def _read_meminfo() -> _MemInfo:
    try:
        return _parse_meminfo(MEMINFO_PATH.read_text())
    except OSError:
        return _MemInfo(0, 0, 0, 0)


def _read_proc_stat() -> tuple[int, int] | None:
    try:
        return _parse_proc_stat(PROC_STAT_PATH.read_text())
    except OSError:
        return None


async def _list_app_containers() -> dict[str, list[str]]:
    """Map compose project name -> full container IDs for every running (incl. paused)
    container, in a single `docker ps` call rather than one per app."""
    out = await subprocess(
        "docker",
        "ps",
        "--no-trunc",
        "--filter",
        f"label={COMPOSE_PROJECT_LABEL}",
        "--format",
        '{{.ID}}\t{{.Label "com.docker.compose.project"}}',
    )
    containers: dict[str, list[str]] = {}
    for line in out.splitlines():
        container_id, _, project = line.strip().partition("\t")
        if container_id and project:
            containers.setdefault(project.strip(), []).append(container_id.strip())
    return containers


def _collect_app_stats(
    apps: list[dict],
    containers_by_project: dict[str, list[str]],
    prev_app_cpu_usec: dict[str, int],
    elapsed_s: float,
) -> tuple[dict[str, AppStats], dict[str, int]]:
    """Sum each app's containers' cgroup memory/CPU and compute the CPU rate.

    Returns the per-app snapshot and the raw cumulative CPU-usec per app, which the
    next sample diffs against.
    """
    new_app_stats: dict[str, AppStats] = {}
    cur_app_cpu_usec: dict[str, int] = {}
    for app in apps:
        name = app["name"]
        project = normalize_project_name(name)
        memory = swap = cpu_usec = 0
        for container_id in containers_by_project.get(project, []):
            cgroup = find_cgroup(container_id)
            if cgroup is None:
                continue
            container_memory, container_swap = _read_cgroup_memory(cgroup)
            memory += container_memory
            swap += container_swap
            cpu_usec += _read_cgroup_cpu_usec(cgroup)
        cur_app_cpu_usec[name] = cpu_usec
        prev = prev_app_cpu_usec.get(name)
        cpu_pct = (
            _cpu_pct(cpu_usec - prev, elapsed_s)
            if prev is not None and elapsed_s > 0
            else 0.0
        )
        new_app_stats[name] = AppStats(
            name=name,
            status=app["status"],
            memory_bytes=memory,
            memory_swap_bytes=swap,
            cpu_pct=cpu_pct,
        )
    return new_app_stats, cur_app_cpu_usec


def _compute_shard_stats(
    meminfo: _MemInfo,
    cpu: tuple[int, int] | None,
    prev_cpu_total: int | None,
    prev_cpu_idle: int | None,
) -> ShardStats:
    cpu_pct = 0.0
    if cpu is not None and prev_cpu_total is not None and prev_cpu_idle is not None:
        total, idle = cpu
        cpu_pct = _cpu_pct_from_jiffies(total - prev_cpu_total, idle - prev_cpu_idle)
    return ShardStats(
        cpu_pct=cpu_pct,
        memory_bytes=meminfo.used_bytes,
        memory_limit_bytes=meminfo.total_bytes,
        memory_swap_bytes=meminfo.swap_used_bytes,
    )


async def update_stats() -> None:
    """Sample all apps and the host once and publish a fresh snapshot."""
    global current_shard_stats, current_app_stats
    global _prev_time, _prev_app_cpu_usec, _prev_cpu_total, _prev_cpu_idle

    now = time.monotonic()
    elapsed = now - _prev_time if _prev_time is not None else 0.0

    async with db_conn() as conn:
        apps = await db_installed_apps.get_all(conn)

    try:
        containers_by_project = await _list_app_containers()
    except SubprocessError as e:
        log.warning(f"could not list containers for metrics: {e}")
        containers_by_project = {}

    new_app_stats, cur_app_cpu_usec = _collect_app_stats(
        apps, containers_by_project, _prev_app_cpu_usec, elapsed
    )

    cpu = _read_proc_stat()
    shard_stats = _compute_shard_stats(
        _read_meminfo(), cpu, _prev_cpu_total, _prev_cpu_idle
    )

    current_app_stats = new_app_stats
    current_shard_stats = shard_stats
    _prev_app_cpu_usec = cur_app_cpu_usec
    _prev_time = now
    if cpu is not None:
        _prev_cpu_total, _prev_cpu_idle = cpu


def get_app_stats(name: str, status: str) -> AppStats:
    """Latest snapshot for one app, or zeros (with the current status) when the app has
    no running containers or the sampler has not reached it yet."""
    stats = current_app_stats.get(name)
    if stats is not None:
        return stats
    return AppStats(
        name=name,
        status=status,
        memory_bytes=0,
        memory_swap_bytes=0,
        cpu_pct=0.0,
    )
