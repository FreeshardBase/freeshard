"""Integration tests for the PAUSED+PAGED tier against real containers.

The pause_cycle mock app carries an empty lifecycle, so both tiers come from
the test config's global defaults (T1=5s pause, T2=12s stop) with the 2s
control-loop refresh.

Not covered here: the memory.reclaim RSS-drop assertion needs root access to
the host cgroup filesystem, which CI and dev runs don't have — the write
logic is unit-tested against a fake cgroup tree in test_memory_pressure.py,
and the actual paging effect is verified in the manual pre-rollout benchmark
(see the design spec's testing strategy).
"""

import time

import docker
from fastapi import status

from shard_core.data_model.app_meta import InstalledApp, Status
from shard_core.service import pause_metrics
from tests.conftest import settings_override
from tests.util import install_app, retry_async, wait_until_app_uninstalled

PAUSE_ON = {"apps": {"lifecycle": {"pause_enabled": True}}}
APP_NAME = "pause_cycle"


def _assert_state(docker_client, api_client):
    async def _get_status():
        response = await api_client.get(f"protected/apps/{APP_NAME}")
        response.raise_for_status()
        return InstalledApp.model_validate(response.json()).status

    def container_status():
        return docker_client.containers.get(APP_NAME).status

    return _get_status, container_status


async def _wake_via_request(api_client):
    response = await api_client.get(
        "internal/auth",
        headers={
            "X-Forwarded-Host": f"{APP_NAME}.myshard.org",
            "X-Forwarded-Uri": "/pub",
        },
    )
    response.raise_for_status()


async def test_full_tier_cycle_and_fast_wake(requests_mock, api_client):
    docker_client = docker.from_env()
    get_status, container_status = _assert_state(docker_client, api_client)

    with settings_override(PAUSE_ON):
        await install_app(api_client, APP_NAME)
        pause_metrics.reset()

        await _wake_via_request(api_client)

        async def assert_running():
            assert container_status() == "running"
            assert await get_status() == Status.RUNNING

        await retry_async(assert_running, timeout=15, retry_errors=[AssertionError])

        # T1: idle >= 5s pauses the containers, status follows
        async def assert_paused():
            assert container_status() == "paused"
            assert await get_status() == Status.PAUSED

        await retry_async(assert_paused, timeout=20, retry_errors=[AssertionError])

        # wake-on-request from PAUSED
        wake_started = time.monotonic()
        await _wake_via_request(api_client)
        await retry_async(assert_running, timeout=10, retry_errors=[AssertionError])
        wake_wall_time = time.monotonic() - wake_started
        # generous ceiling for loaded CI runners; the precise target is pinned
        # on the recorded unpause latency below
        assert wake_wall_time < 10

        # the compose unpause itself must be fast (design target: <=2s p95)
        assert pause_metrics.unpause_latencies_ms
        assert pause_metrics.unpause_latencies_ms[-1] < 2000

        # T2: after another T1 the app re-pauses, after idle >= 12s it stops
        await retry_async(assert_paused, timeout=20, retry_errors=[AssertionError])

        async def assert_stopped():
            assert container_status() == "exited"
            assert await get_status() == Status.STOPPED

        await retry_async(assert_stopped, timeout=25, retry_errors=[AssertionError])

        # transitions were recorded for telemetry
        transitions = pause_metrics.app_transitions[APP_NAME]
        assert transitions["running_to_paused"] >= 2
        assert transitions["paused_to_running"] >= 1
        assert transitions["paused_to_stopped"] >= 1


async def test_uninstall_while_paused(requests_mock, api_client):
    docker_client = docker.from_env()
    get_status, container_status = _assert_state(docker_client, api_client)

    with settings_override(PAUSE_ON):
        await install_app(api_client, APP_NAME)
        await _wake_via_request(api_client)

        async def assert_paused():
            assert container_status() == "paused"
            assert await get_status() == Status.PAUSED

        await retry_async(assert_paused, timeout=25, retry_errors=[AssertionError])

        # uninstalling a frozen stack must unfreeze before stop/down
        response = await api_client.delete(f"protected/apps/{APP_NAME}")
        assert response.status_code == status.HTTP_204_NO_CONTENT
        await wait_until_app_uninstalled(api_client, APP_NAME)

        async def assert_gone():
            try:
                docker_client.containers.get(APP_NAME)
            except docker.errors.NotFound:
                return
            raise AssertionError(f"container {APP_NAME} still exists")

        await retry_async(assert_gone, timeout=15, retry_errors=[AssertionError])
