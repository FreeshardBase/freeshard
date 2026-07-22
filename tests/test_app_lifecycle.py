from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import docker
from fastapi import status

from shard_core.data_model.app_meta import AppMeta, InstalledApp, Lifecycle, Status
from shard_core.service import app_lifecycle
from tests.util import retry_async, wait_until_app_installed


async def test_app_starts_and_stops(requests_mock, api_client):
    docker_client = docker.from_env()
    app_name = "quick_stop"

    response = await api_client.post(f"protected/apps/{app_name}")
    assert response.status_code == status.HTTP_201_CREATED

    await wait_until_app_installed(api_client, app_name)

    assert docker_client.containers.get(app_name).status == "created"
    assert (
        InstalledApp.model_validate(
            (await api_client.get(f"protected/apps/{app_name}")).json()
        ).status
        == Status.STOPPED
    )

    response = await api_client.get(
        "internal/auth",
        headers={
            "X-Forwarded-Host": f"{app_name}.myshard.org",
            "X-Forwarded-Uri": "/pub",
        },
    )
    response.raise_for_status()

    async def assert_app_running():
        assert docker_client.containers.get(app_name).status == "running"
        assert (
            InstalledApp.model_validate(
                (await api_client.get(f"protected/apps/{app_name}")).json()
            ).status
            == Status.RUNNING
        )

    async def assert_app_exited():
        assert docker_client.containers.get(app_name).status == "exited"
        assert (
            InstalledApp.model_validate(
                (await api_client.get(f"protected/apps/{app_name}")).json()
            ).status
            == Status.STOPPED
        )

    await retry_async(assert_app_running, timeout=10, retry_errors=[AssertionError])
    await retry_async(assert_app_exited, timeout=15, retry_errors=[AssertionError])

    response = await api_client.get(
        "internal/auth",
        headers={
            "X-Forwarded-Host": f"{app_name}.myshard.org",
            "X-Forwarded-Uri": "/pub",
        },
    )
    response.raise_for_status()

    await retry_async(assert_app_running, timeout=10, retry_errors=[AssertionError])
    assert (
        InstalledApp.model_validate(
            (await api_client.get(f"protected/apps/{app_name}")).json()
        ).status
        == Status.RUNNING
    )
    await retry_async(assert_app_exited, timeout=10, retry_errors=[AssertionError])
    assert (
        InstalledApp.model_validate(
            (await api_client.get(f"protected/apps/{app_name}")).json()
        ).status
        == Status.STOPPED
    )


async def test_always_on_app_starts(requests_mock, api_client):
    docker_client = docker.from_env()
    app_name = "always_on"

    response = await api_client.post(f"protected/apps/{app_name}")
    assert response.status_code == status.HTTP_201_CREATED

    await wait_until_app_installed(api_client, app_name)

    async def assert_app_running():
        assert docker_client.containers.get(app_name).status == "running"
        assert (
            InstalledApp.model_validate(
                (await api_client.get(f"protected/apps/{app_name}")).json()
            ).status
            == Status.RUNNING
        )

    await retry_async(assert_app_running, timeout=30, retry_errors=[AssertionError])


# todo: test_large_app_does_not_start

# todo: test app with size comparison


# Idle-stop reads the DB last_access column (installed_apps.last_access), which
# is the single source of truth since #133 replaced the in-memory dict. The
# app object passed to _control_app_time is the one control_apps loads from the
# DB, so setting InstalledApp.last_access here pins the column-driven decision.
# tests/config.toml: default_idle_for_stop=12.


def _idle_meta() -> AppMeta:
    return AppMeta(
        v="1.3",
        app_version="1.0.0",
        name="test",
        pretty_name="Test",
        icon="icon.svg",
        entrypoints=[],
        paths={},
        lifecycle=Lifecycle(),
    )


async def test_idle_stop_uses_last_access_when_stale():
    app = InstalledApp(
        name="a",
        status=Status.RUNNING,
        last_access=datetime.now(timezone.utc) - timedelta(seconds=20),
    )
    with (
        patch.object(app_lifecycle, "docker_stop_app", new=AsyncMock()) as stop,
        patch.object(app_lifecycle, "get_app_metadata", return_value=_idle_meta()),
    ):
        await app_lifecycle._control_app_time(app, pause_enabled=False)
    stop.assert_awaited_once_with("a")


async def test_idle_stop_leaves_recently_accessed_app_running():
    app = InstalledApp(
        name="a",
        status=Status.RUNNING,
        last_access=datetime.now(timezone.utc),
    )
    with (
        patch.object(app_lifecycle, "docker_stop_app", new=AsyncMock()) as stop,
        patch.object(app_lifecycle, "get_app_metadata", return_value=_idle_meta()),
    ):
        await app_lifecycle._control_app_time(app, pause_enabled=False)
    stop.assert_not_awaited()


async def test_never_accessed_running_app_is_treated_as_idle():
    app = InstalledApp(name="a", status=Status.RUNNING, last_access=None)
    with (
        patch.object(app_lifecycle, "docker_stop_app", new=AsyncMock()) as stop,
        patch.object(app_lifecycle, "get_app_metadata", return_value=_idle_meta()),
    ):
        await app_lifecycle._control_app_time(app, pause_enabled=False)
    stop.assert_awaited_once_with("a")
