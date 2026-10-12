from pathlib import Path

import pytest
from fastapi import status

from shard_core.data_model.app_meta import InstallationReason, InstalledApp, Status
from shard_core.database import installed_apps as db_installed_apps
from shard_core.database.connection import db_conn
from shard_core.service import metrics
from shard_core.service.metrics import AppStats, ShardStats, _MemInfo
from shard_core.util.subprocess import SubprocessError


@pytest.fixture(autouse=True)
def _reset_metrics_state():
    """The snapshot and CPU-delta bookkeeping are module globals; restore them after
    each test so a direct `update_stats` call (or a set snapshot) does not leak."""
    saved = (
        metrics.current_shard_stats,
        dict(metrics.current_app_stats),
        metrics._prev_time,
        dict(metrics._prev_app_cpu_usec),
        metrics._prev_cpu_total,
        metrics._prev_cpu_idle,
        metrics._container_list_failed,
    )
    yield
    (
        metrics.current_shard_stats,
        metrics.current_app_stats,
        metrics._prev_time,
        metrics._prev_app_cpu_usec,
        metrics._prev_cpu_total,
        metrics._prev_cpu_idle,
        metrics._container_list_failed,
    ) = saved


def _write_cgroup(
    cgroup: Path, *, current=None, swap=None, cpu_usec=None
) -> Path:
    cgroup.mkdir(parents=True, exist_ok=True)
    if current is not None:
        (cgroup / "memory.current").write_text(f"{current}\n")
    if swap is not None:
        (cgroup / "memory.swap.current").write_text(f"{swap}\n")
    if cpu_usec is not None:
        (cgroup / "cpu.stat").write_text(f"usage_usec {cpu_usec}\nuser_usec 10\n")
    return cgroup


# --- /proc parsing -----------------------------------------------------------

PROC_STAT_SAMPLE = """cpu  100 0 50 800 50 0 0 0 0 0
cpu0 50 0 25 400 25 0 0 0 0 0
intr 1234
"""


def test_parse_proc_stat_sums_total_and_idle():
    total, idle = metrics._parse_proc_stat(PROC_STAT_SAMPLE)
    assert total == 1000  # sum of all 10 fields
    assert idle == 850  # idle + iowait


def test_parse_proc_stat_without_cpu_line_returns_none():
    assert metrics._parse_proc_stat("intr 1\nctxt 2\n") is None


MEMINFO_SAMPLE = """MemTotal:        2000 kB
MemFree:          500 kB
MemAvailable:    1200 kB
SwapTotal:        1000 kB
SwapFree:         400 kB
"""


def test_parse_meminfo_uses_available_and_swap():
    mi = metrics._parse_meminfo(MEMINFO_SAMPLE)
    assert mi.total_bytes == 2000 * 1024
    assert mi.available_bytes == 1200 * 1024
    assert mi.used_bytes == 800 * 1024
    assert mi.swap_used_bytes == 600 * 1024


def test_parse_meminfo_falls_back_to_memfree():
    mi = metrics._parse_meminfo("MemTotal: 2000 kB\nMemFree: 500 kB\n")
    assert mi.available_bytes == 500 * 1024
    assert mi.used_bytes == 1500 * 1024
    assert mi.swap_used_bytes == 0


def test_meminfo_used_bytes_clamps_when_available_exceeds_total():
    # MemAvailable is a kernel estimate and can briefly exceed MemTotal.
    assert _MemInfo(total_bytes=100, available_bytes=150, swap_total_bytes=0, swap_free_bytes=0).used_bytes == 0


# --- CPU percentage ----------------------------------------------------------


def test_cpu_pct_one_full_core_is_100():
    assert metrics._cpu_pct(1_000_000, 1.0) == 100.0


def test_cpu_pct_can_exceed_100_on_multiple_cores():
    assert metrics._cpu_pct(2_000_000, 1.0) == 200.0


def test_cpu_pct_guards_against_zero_interval_and_negative_delta():
    assert metrics._cpu_pct(1000, 0.0) == 0.0
    # A container restart resets its cumulative usage_usec, yielding a large negative
    # delta; without the guard this would be -100.0, not 0.0.
    assert metrics._cpu_pct(-1_000_000, 1.0) == 0.0


def test_cpu_pct_from_jiffies():
    # busy = total - idle = 1000 - 850 = 150 -> 15%
    assert metrics._cpu_pct_from_jiffies(1000, 850) == 15.0


def test_cpu_pct_from_jiffies_zero_total():
    assert metrics._cpu_pct_from_jiffies(0, 0) == 0.0


def test_cpu_pct_from_jiffies_clamps_negative_busy():
    # Per-CPU rounding on the aggregate line can make idle_delta exceed total_delta;
    # the result must clamp to 0, not go negative.
    assert metrics._cpu_pct_from_jiffies(100, 150) == 0.0


# --- cgroup reads ------------------------------------------------------------


def test_read_cgroup_memory(tmp_path):
    _write_cgroup(tmp_path, current=1024, swap=512)
    assert metrics._read_cgroup_memory(tmp_path) == (1024, 512)


def test_read_cgroup_memory_missing_files_returns_zeros(tmp_path):
    assert metrics._read_cgroup_memory(tmp_path) == (0, 0)


def test_read_cgroup_cpu_usec(tmp_path):
    _write_cgroup(tmp_path, cpu_usec=123456)
    assert metrics._read_cgroup_cpu_usec(tmp_path) == 123456


def test_read_cgroup_cpu_usec_missing_returns_zero(tmp_path):
    assert metrics._read_cgroup_cpu_usec(tmp_path) == 0


# --- per-app collection ------------------------------------------------------


def test_collect_app_stats_sums_containers_and_computes_cpu(tmp_path, monkeypatch):
    c1 = _write_cgroup(tmp_path / "c1", current=1000, swap=100, cpu_usec=500_000)
    c2 = _write_cgroup(tmp_path / "c2", current=2000, swap=200, cpu_usec=1_500_000)
    cgroups = {"c1id": c1, "c2id": c2}
    monkeypatch.setattr(metrics, "find_cgroup", lambda cid: cgroups.get(cid))

    apps = [{"name": "myapp", "status": "running"}]
    containers = {"myapp": ["c1id", "c2id"]}

    # First sample: no previous reading, so CPU is reported as 0.
    stats, cur = metrics._collect_app_stats(apps, containers, {}, 0.0)
    assert stats["myapp"].memory_bytes == 3000
    assert stats["myapp"].memory_swap_bytes == 300
    assert stats["myapp"].cpu_pct == 0.0
    assert cur["myapp"] == 2_000_000

    # Second sample: 2_000_000 usec of CPU over 1s wall clock -> 200% (two cores).
    stats2, _ = metrics._collect_app_stats(apps, containers, {"myapp": 0}, 1.0)
    assert stats2["myapp"].cpu_pct == 200.0


def test_collect_app_stats_app_without_running_containers_is_zero():
    apps = [{"name": "idle", "status": "stopped"}]
    stats, cur = metrics._collect_app_stats(apps, {}, {}, 1.0)
    assert stats["idle"].memory_bytes == 0
    assert stats["idle"].memory_swap_bytes == 0
    assert stats["idle"].cpu_pct == 0.0
    assert cur["idle"] == 0


def test_collect_app_stats_skips_container_without_cgroup(monkeypatch):
    monkeypatch.setattr(metrics, "find_cgroup", lambda cid: None)
    apps = [{"name": "ghost", "status": "running"}]
    stats, _ = metrics._collect_app_stats(apps, {"ghost": ["missing"]}, {}, 1.0)
    assert stats["ghost"].memory_bytes == 0


# --- shard rollup ------------------------------------------------------------


def test_compute_shard_stats_first_sample_has_zero_cpu():
    mi = _MemInfo(2000, 1200, 1000, 400)
    shard = metrics._compute_shard_stats(mi, (1000, 850), None, None)
    assert shard.cpu_pct == 0.0
    assert shard.memory_bytes == 800
    assert shard.memory_limit_bytes == 2000
    assert shard.memory_swap_bytes == 600


def test_compute_shard_stats_cpu_delta():
    mi = _MemInfo(0, 0, 0, 0)
    # total 1000 -> 2000 (delta 1000); idle 850 -> 1700 (delta 850); busy 150 -> 15%.
    shard = metrics._compute_shard_stats(mi, (2000, 1700), 1000, 850)
    assert shard.cpu_pct == 15.0


# --- endpoints ---------------------------------------------------------------


async def test_shard_stats_endpoint(app_client):
    metrics.current_shard_stats = ShardStats(
        cpu_pct=12.5, memory_bytes=1000, memory_limit_bytes=4000, memory_swap_bytes=50
    )
    resp = await app_client.get("protected/stats")
    assert resp.status_code == status.HTTP_200_OK
    assert resp.json() == {
        "cpu_pct": 12.5,
        "memory_bytes": 1000,
        "memory_limit_bytes": 4000,
        "memory_swap_bytes": 50,
    }
    # The new empty-path route must not shadow the sibling /stats/disk route.
    disk_resp = await app_client.get("protected/stats/disk")
    assert disk_resp.status_code == status.HTTP_200_OK
    assert "disk_space_low" in disk_resp.json()


async def test_app_stats_endpoint_unknown_app_is_404(app_client):
    resp = await app_client.get("protected/apps/does-not-exist/stats")
    assert resp.status_code == status.HTTP_404_NOT_FOUND


async def _insert_app(name: str, app_status: Status):
    async with db_conn() as conn:
        await db_installed_apps.insert(
            conn,
            InstalledApp(
                name=name,
                installation_reason=InstallationReason.CUSTOM,
                status=app_status,
            ).model_dump(),
        )


async def test_app_stats_endpoint_serves_snapshot(app_client):
    await _insert_app("app_x", Status.RUNNING)
    metrics.current_app_stats = {
        "app_x": AppStats(
            name="app_x",
            status="running",
            memory_bytes=2048,
            memory_swap_bytes=16,
            cpu_pct=5.0,
        )
    }
    resp = await app_client.get("protected/apps/app_x/stats")
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert data["name"] == "app_x"
    assert data["memory_bytes"] == 2048
    assert data["memory_swap_bytes"] == 16
    assert data["cpu_pct"] == 5.0


async def test_app_stats_endpoint_overlays_fresh_db_status_on_snapshot(app_client):
    # DB says stopped, but the (up to one interval old) snapshot still says running.
    await _insert_app("app_s", Status.STOPPED)
    metrics.current_app_stats = {
        "app_s": AppStats(
            name="app_s",
            status="running",
            memory_bytes=512,
            memory_swap_bytes=0,
            cpu_pct=1.0,
        )
    }
    resp = await app_client.get("protected/apps/app_s/stats")
    data = resp.json()
    assert data["status"] == "stopped"  # DB-fresh, not the stale snapshot value
    assert data["memory_bytes"] == 512  # sampled memory still served


async def test_app_stats_endpoint_installed_but_not_sampled_returns_zeros(app_client):
    await _insert_app("app_y", Status.STOPPED)
    metrics.current_app_stats = {}
    resp = await app_client.get("protected/apps/app_y/stats")
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert data["status"] == "stopped"
    assert data["memory_bytes"] == 0
    assert data["cpu_pct"] == 0.0


async def test_update_stats_populates_snapshot(app_client, tmp_path, monkeypatch):
    await _insert_app("app_z", Status.RUNNING)
    cgroup = _write_cgroup(tmp_path / "cg", current=4096, swap=10, cpu_usec=1_000_000)

    async def fake_list_containers():
        return {"app_z": ["zid"]}

    monkeypatch.setattr(metrics, "_list_app_containers", fake_list_containers)
    monkeypatch.setattr(metrics, "find_cgroup", lambda cid: cgroup if cid == "zid" else None)

    proc_stat = tmp_path / "stat"
    proc_stat.write_text("cpu  100 0 50 800 50 0 0 0 0 0\n")
    meminfo = tmp_path / "meminfo"
    meminfo.write_text(
        "MemTotal: 2000 kB\nMemAvailable: 1200 kB\nSwapTotal: 0 kB\nSwapFree: 0 kB\n"
    )
    monkeypatch.setattr(metrics, "PROC_STAT_PATH", proc_stat)
    monkeypatch.setattr(metrics, "MEMINFO_PATH", meminfo)

    metrics._prev_time = None
    metrics._prev_app_cpu_usec = {}
    metrics._prev_cpu_total = None
    metrics._prev_cpu_idle = None

    await metrics.update_stats()

    assert metrics.current_app_stats["app_z"].memory_bytes == 4096
    assert metrics.current_app_stats["app_z"].memory_swap_bytes == 10
    assert metrics.current_shard_stats.memory_limit_bytes == 2000 * 1024
    assert metrics.current_shard_stats.memory_bytes == 800 * 1024

    resp = await app_client.get("protected/apps/app_z/stats")
    assert resp.json()["memory_bytes"] == 4096

    # First sample has no previous reading, so CPU is 0; a second sample with a higher
    # cumulative usage_usec carries the bookkeeping forward and reports non-zero CPU.
    assert metrics.current_app_stats["app_z"].cpu_pct == 0.0
    _write_cgroup(cgroup, cpu_usec=3_000_000)
    await metrics.update_stats()
    assert metrics.current_app_stats["app_z"].cpu_pct > 0.0


async def test_update_stats_survives_docker_failure_and_logs_once(app_client, monkeypatch):
    await _insert_app("app_f", Status.RUNNING)

    async def failing_list():
        raise SubprocessError("docker ps boom")

    monkeypatch.setattr(metrics, "_list_app_containers", failing_list)
    metrics._container_list_failed = False

    await metrics.update_stats()
    # Apps are still enumerated (from the DB); they just have no container metrics.
    assert metrics._container_list_failed is True
    assert metrics.current_app_stats["app_f"].memory_bytes == 0

    # Recovery clears the warn-once flag.
    async def empty_list():
        return {}

    monkeypatch.setattr(metrics, "_list_app_containers", empty_list)
    await metrics.update_stats()
    assert metrics._container_list_failed is False
