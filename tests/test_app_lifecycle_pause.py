"""Unit tests for the two-tier idle logic and PSI-driven LRU demotion.

The docker primitives and metadata lookups are patched — these tests pin the
decision logic of _control_app_time and _demote_lru, not Docker behavior
(that lives in the integration tests).
"""

import asyncio
import time
from unittest.mock import AsyncMock, patch

import pytest

from shard_core.data_model.app_meta import (
    AppMeta,
    InstalledApp,
    Lifecycle,
    Status,
)
from shard_core.service import app_lifecycle
from tests.conftest import settings_override


def _meta(lifecycle: Lifecycle) -> AppMeta:
    return AppMeta(
        v="1.3",
        app_version="1.0.0",
        name="test",
        pretty_name="Test",
        icon="icon.svg",
        entrypoints=[],
        paths={},
        lifecycle=lifecycle,
    )


@pytest.fixture
def docker_mocks():
    with (
        patch.object(app_lifecycle, "start_app", new=AsyncMock()) as start,
        patch.object(app_lifecycle, "docker_stop_app", new=AsyncMock()) as stop,
        patch.object(app_lifecycle, "docker_pause_app", new=AsyncMock()) as pause,
        patch.object(
            app_lifecycle, "size_is_compatible", new=AsyncMock(return_value=True)
        ),
    ):
        yield {"start": start, "stop": stop, "pause": pause}


@pytest.fixture(autouse=True)
def clean_last_access():
    app_lifecycle.last_access_dict.clear()
    yield
    app_lifecycle.last_access_dict.clear()


def _app(name: str, status: Status, idle: float) -> InstalledApp:
    app_lifecycle.last_access_dict[name] = time.time() - idle
    return InstalledApp(name=name, status=status)


PAUSE_ON = {"apps": {"lifecycle": {"pause_enabled": True}}}
# tests/config.toml: default_idle_for_pause=5, default_idle_for_stop=12


@pytest.mark.parametrize(
    "status", [Status.PAUSED, Status.STOPPED, Status.DOWN, Status.RUNNING]
)
async def test_wake_routes_every_status_through_start_app(docker_mocks, status):
    # Previously a PAUSED app woke via docker_unpause_app, which 502-looped when
    # the container had actually exited (#185). Every status now goes through the
    # one real-state revive primitive.
    app = _app("a", status, idle=0)
    with (
        settings_override(PAUSE_ON),
        patch.object(
            app_lifecycle, "get_app_metadata", return_value=_meta(Lifecycle())
        ),
        patch.object(
            app_lifecycle.disk,
            "current_disk_usage",
            app_lifecycle.disk.DiskUsage(total_gb=10, free_gb=9, disk_space_low=False),
        ),
    ):
        await app_lifecycle.ensure_app_is_running(app)
        await asyncio.sleep(0)
    docker_mocks["start"].assert_awaited_once_with("a")


async def test_running_app_pauses_after_t1(docker_mocks):
    app = _app("a", Status.RUNNING, idle=7)
    with (
        settings_override(PAUSE_ON),
        patch.object(
            app_lifecycle, "get_app_metadata", return_value=_meta(Lifecycle())
        ),
    ):
        await app_lifecycle._control_app_time(app, pause_enabled=True)
    docker_mocks["pause"].assert_awaited_once_with("a")
    docker_mocks["stop"].assert_not_awaited()


async def test_running_app_below_t1_is_left_alone(docker_mocks):
    app = _app("a", Status.RUNNING, idle=2)
    with (
        settings_override(PAUSE_ON),
        patch.object(
            app_lifecycle, "get_app_metadata", return_value=_meta(Lifecycle())
        ),
    ):
        await app_lifecycle._control_app_time(app, pause_enabled=True)
    docker_mocks["pause"].assert_not_awaited()
    docker_mocks["stop"].assert_not_awaited()


async def test_paused_app_stops_after_t2(docker_mocks):
    app = _app("a", Status.PAUSED, idle=15)
    with (
        settings_override(PAUSE_ON),
        patch.object(
            app_lifecycle, "get_app_metadata", return_value=_meta(Lifecycle())
        ),
    ):
        await app_lifecycle._control_app_time(app, pause_enabled=True)
    docker_mocks["stop"].assert_awaited_once_with("a")
    docker_mocks["pause"].assert_not_awaited()


async def test_paused_app_below_t2_stays_paused(docker_mocks):
    app = _app("a", Status.PAUSED, idle=7)
    with (
        settings_override(PAUSE_ON),
        patch.object(
            app_lifecycle, "get_app_metadata", return_value=_meta(Lifecycle())
        ),
    ):
        await app_lifecycle._control_app_time(app, pause_enabled=True)
    docker_mocks["stop"].assert_not_awaited()
    docker_mocks["pause"].assert_not_awaited()


async def test_flag_off_keeps_legacy_stop_only(docker_mocks):
    app = _app("a", Status.RUNNING, idle=15)
    with patch.object(
        app_lifecycle, "get_app_metadata", return_value=_meta(Lifecycle())
    ):
        await app_lifecycle._control_app_time(app, pause_enabled=False)
    docker_mocks["stop"].assert_awaited_once_with("a")
    docker_mocks["pause"].assert_not_awaited()


async def test_skip_pause_app_never_pauses(docker_mocks):
    app = _app("a", Status.RUNNING, idle=15)
    with (
        settings_override(PAUSE_ON),
        patch.object(
            app_lifecycle,
            "get_app_metadata",
            return_value=_meta(Lifecycle(skip_pause=True)),
        ),
    ):
        await app_lifecycle._control_app_time(app, pause_enabled=True)
    docker_mocks["stop"].assert_awaited_once_with("a")
    docker_mocks["pause"].assert_not_awaited()


async def test_per_app_idle_overrides_win(docker_mocks):
    # per-app t1=60 keeps the app running where the global default (5) would pause
    app = _app("a", Status.RUNNING, idle=10)
    with (
        settings_override(PAUSE_ON),
        patch.object(
            app_lifecycle,
            "get_app_metadata",
            return_value=_meta(Lifecycle(idle_for_pause=60, idle_for_stop=120)),
        ),
    ):
        await app_lifecycle._control_app_time(app, pause_enabled=True)
    docker_mocks["pause"].assert_not_awaited()
    docker_mocks["stop"].assert_not_awaited()


async def test_always_on_app_is_started_not_paused(docker_mocks):
    app = _app("a", Status.STOPPED, idle=9999)
    with (
        settings_override(PAUSE_ON),
        patch.object(
            app_lifecycle,
            "get_app_metadata",
            return_value=_meta(Lifecycle(always_on=True)),
        ),
    ):
        await app_lifecycle._control_app_time(app, pause_enabled=True)
    docker_mocks["start"].assert_awaited_once_with("a")
    docker_mocks["pause"].assert_not_awaited()
    docker_mocks["stop"].assert_not_awaited()


async def test_low_disk_stops_even_always_on_apps(docker_mocks):
    app = _app("a", Status.RUNNING, idle=0)
    with (
        settings_override(PAUSE_ON),
        patch.object(
            app_lifecycle,
            "get_app_metadata",
            return_value=_meta(Lifecycle(always_on=True)),
        ),
        patch.object(
            app_lifecycle.disk,
            "current_disk_usage",
            app_lifecycle.disk.DiskUsage(total_gb=10, free_gb=0.1, disk_space_low=True),
        ),
    ):
        await app_lifecycle._control_app_time(app, pause_enabled=True)
    docker_mocks["stop"].assert_awaited_once_with("a")
    docker_mocks["start"].assert_not_awaited()
    docker_mocks["pause"].assert_not_awaited()


async def test_demote_lru_pauses_least_recently_used_running_app(docker_mocks):
    apps = [
        _app("newer", Status.RUNNING, idle=100),
        _app("older", Status.RUNNING, idle=200),
    ]
    with patch.object(
        app_lifecycle, "get_app_metadata", return_value=_meta(Lifecycle())
    ):
        await app_lifecycle._demote_lru(apps)
    docker_mocks["pause"].assert_awaited_once_with("older")
    docker_mocks["stop"].assert_not_awaited()


async def test_demote_lru_prefers_pausing_running_over_stopping_paused(docker_mocks):
    # the paused app is older, but pausing a running app has less user impact
    # than stopping a paused one — running apps are demoted first
    apps = [
        _app("running", Status.RUNNING, idle=100),
        _app("paused", Status.PAUSED, idle=200),
    ]
    with patch.object(
        app_lifecycle, "get_app_metadata", return_value=_meta(Lifecycle())
    ):
        await app_lifecycle._demote_lru(apps)
    docker_mocks["pause"].assert_awaited_once_with("running")
    docker_mocks["stop"].assert_not_awaited()


async def test_demote_lru_stops_lru_paused_when_nothing_left_to_pause(docker_mocks):
    apps = [
        _app("paused_newer", Status.PAUSED, idle=100),
        _app("paused_older", Status.PAUSED, idle=200),
    ]
    with patch.object(
        app_lifecycle, "get_app_metadata", return_value=_meta(Lifecycle())
    ):
        await app_lifecycle._demote_lru(apps)
    docker_mocks["stop"].assert_awaited_once_with("paused_older")
    docker_mocks["pause"].assert_not_awaited()


async def test_demote_lru_stops_running_skip_pause_victim(docker_mocks):
    apps = [_app("a", Status.RUNNING, idle=200)]
    with patch.object(
        app_lifecycle,
        "get_app_metadata",
        return_value=_meta(Lifecycle(skip_pause=True)),
    ):
        await app_lifecycle._demote_lru(apps)
    docker_mocks["stop"].assert_awaited_once_with("a")
    docker_mocks["pause"].assert_not_awaited()


async def test_demote_lru_excludes_always_on_recent_and_stopped(docker_mocks):
    metas = {
        "always_on": _meta(Lifecycle(always_on=True)),
        "recent": _meta(Lifecycle()),
        "stopped": _meta(Lifecycle()),
    }
    apps = [
        _app("always_on", Status.RUNNING, idle=500),
        _app("recent", Status.RUNNING, idle=1),  # within RECENT_ACCESS_GRACE
        _app("stopped", Status.STOPPED, idle=500),
    ]
    with patch.object(
        app_lifecycle, "get_app_metadata", side_effect=lambda name: metas[name]
    ):
        await app_lifecycle._demote_lru(apps)
    docker_mocks["pause"].assert_not_awaited()
    docker_mocks["stop"].assert_not_awaited()


async def test_demote_lru_demotes_exactly_one_app_per_cycle(docker_mocks):
    apps = [
        _app("a", Status.RUNNING, idle=300),
        _app("b", Status.RUNNING, idle=200),
        _app("c", Status.RUNNING, idle=100),
    ]
    with patch.object(
        app_lifecycle, "get_app_metadata", return_value=_meta(Lifecycle())
    ):
        await app_lifecycle._demote_lru(apps)
    assert docker_mocks["pause"].await_count == 1
    docker_mocks["pause"].assert_awaited_once_with("a")
