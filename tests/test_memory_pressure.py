import errno
import logging
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from shard_core.service import memory_pressure

PSI_SAMPLE = """some avg10=12.34 avg60=5.67 avg300=1.23 total=123456
full avg10=3.21 avg60=1.11 avg300=0.42 total=65432
"""


def test_read_memory_pressure_parses_some_avg10(tmp_path, monkeypatch):
    psi_file = tmp_path / "memory"
    psi_file.write_text(PSI_SAMPLE)
    monkeypatch.setattr(memory_pressure, "PSI_PATH", psi_file)
    assert memory_pressure.read_memory_pressure() == 12.34


def test_read_memory_pressure_missing_file_returns_zero(tmp_path, monkeypatch):
    monkeypatch.setattr(memory_pressure, "PSI_PATH", tmp_path / "does-not-exist")
    assert memory_pressure.read_memory_pressure() == 0.0


def test_read_memory_pressure_malformed_returns_zero(tmp_path, monkeypatch):
    psi_file = tmp_path / "memory"
    psi_file.write_text("garbage that is not PSI\n")
    monkeypatch.setattr(memory_pressure, "PSI_PATH", psi_file)
    assert memory_pressure.read_memory_pressure() == 0.0


@pytest.fixture
def fake_cgroup_root(tmp_path, monkeypatch):
    monkeypatch.setattr(memory_pressure, "CGROUP_ROOT", tmp_path)
    return tmp_path


def _make_cgroup(root, relative: str, memory_current: int):
    cgroup = root / relative
    cgroup.mkdir(parents=True)
    (cgroup / "memory.current").write_text(f"{memory_current}\n")
    (cgroup / "memory.reclaim").write_text("")
    return cgroup


def test_reclaim_container_writes_rss_systemd_driver(fake_cgroup_root):
    cgroup = _make_cgroup(
        fake_cgroup_root, "system.slice/docker-abc123.scope", 104857600
    )
    memory_pressure._reclaim_container("abc123")
    assert (cgroup / "memory.reclaim").read_text() == "104857600\n"


def test_reclaim_container_writes_rss_cgroupfs_driver(fake_cgroup_root):
    cgroup = _make_cgroup(fake_cgroup_root, "docker/def456", 2048)
    memory_pressure._reclaim_container("def456")
    assert (cgroup / "memory.reclaim").read_text() == "2048\n"


def test_reclaim_container_missing_cgroup_is_skipped(fake_cgroup_root):
    # must not raise
    memory_pressure._reclaim_container("unknown")


def test_reclaim_container_zero_usage_writes_nothing(fake_cgroup_root):
    cgroup = _make_cgroup(fake_cgroup_root, "docker/ghi789", 0)
    memory_pressure._reclaim_container("ghi789")
    assert (cgroup / "memory.reclaim").read_text() == ""


def test_reclaim_container_eagain_is_debug_not_warning(
    fake_cgroup_root, caplog, monkeypatch
):
    # Requesting the full RSS always ends in EAGAIN once nothing more can be
    # paged out — expected on every pause, so it must not log a warning.
    _make_cgroup(fake_cgroup_root, "docker/eag123", 4096)

    def _raise_eagain(self, *args, **kwargs):
        raise OSError(errno.EAGAIN, "write could not complete without blocking")

    monkeypatch.setattr(Path, "write_text", _raise_eagain)
    with caplog.at_level(logging.DEBUG):
        memory_pressure._reclaim_container("eag123")

    assert not any(r.levelno == logging.WARNING for r in caplog.records)
    assert any("EAGAIN" in r.getMessage() for r in caplog.records)


def test_reclaim_container_other_oserror_warns(fake_cgroup_root, caplog, monkeypatch):
    # A genuine error (not EAGAIN) still surfaces as a warning.
    _make_cgroup(fake_cgroup_root, "docker/err123", 4096)

    def _raise_eperm(self, *args, **kwargs):
        raise OSError(errno.EPERM, "operation not permitted")

    monkeypatch.setattr(Path, "write_text", _raise_eperm)
    with caplog.at_level(logging.DEBUG):
        memory_pressure._reclaim_container("err123")

    assert any(
        r.levelno == logging.WARNING and "failed" in r.getMessage()
        for r in caplog.records
    )


async def test_reclaim_compose_stack_reclaims_each_container(fake_cgroup_root):
    cgroup_a = _make_cgroup(fake_cgroup_root, "docker/aaa", 100)
    cgroup_b = _make_cgroup(fake_cgroup_root, "docker/bbb", 200)
    with patch.object(
        memory_pressure, "subprocess", new=AsyncMock(return_value="aaa\nbbb\n\n")
    ):
        await memory_pressure.reclaim_compose_stack("someapp")
    assert (cgroup_a / "memory.reclaim").read_text() == "100\n"
    assert (cgroup_b / "memory.reclaim").read_text() == "200\n"
