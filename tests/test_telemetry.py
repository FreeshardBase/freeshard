import json

from shard_core.data_model.backend.telemetry_model import Telemetry
from shard_core.service import telemetry
from unittest.mock import AsyncMock, patch

from tests.conftest import settings_override
from shard_core.util.signals import on_terminal_auth, on_request_to_app


async def test_telemetry_recording(app_client):
    # Verify signal wiring: record_request is connected to both signals
    assert telemetry.record_request in on_terminal_auth.receivers_for(None)
    assert telemetry.record_request in on_request_to_app.receivers_for(None)

    # Verify counter increments
    await telemetry.record_request("test")
    await telemetry.record_request("test")
    assert telemetry.no_of_requests == 2


@patch("shard_core.service.telemetry.call_freeshard_controller", new_callable=AsyncMock)
async def test_telemetry_sending(mock_call_freeshard_controller: AsyncMock, app_client):
    for i in range(3):
        await telemetry.record_request("arg")
    await telemetry.send_telemetry()

    assert mock_call_freeshard_controller.called
    body = mock_call_freeshard_controller.await_args_list[0].kwargs["body"]
    tel = Telemetry.model_validate(json.loads(body.decode()))
    assert tel.no_of_requests == 3


async def test_telemetry_sending_failure(app_client):
    with settings_override(
        {"freeshard_controller": {"base_url": "https://non-existing.com"}}
    ):
        await telemetry.record_request("arg")
        await telemetry.send_telemetry()


@patch("shard_core.service.telemetry.call_freeshard_controller", new_callable=AsyncMock)
async def test_telemetry_disabled(
    mock_call_freeshard_controller: AsyncMock, app_client
):
    with settings_override({"telemetry": {"enabled": False}}):
        await telemetry.record_request("arg")
        await telemetry.send_telemetry()

        assert telemetry.no_of_requests == 0
        assert not mock_call_freeshard_controller.called


@patch("shard_core.service.telemetry.call_freeshard_controller", new_callable=AsyncMock)
async def test_telemetry_pause_tier_roundtrip(
    mock_call_freeshard_controller: AsyncMock, app_client
):
    from shard_core.data_model.app_meta import Status
    from shard_core.service import pause_metrics

    pause_metrics.reset()
    pause_metrics.record_app_transition("immich", Status.RUNNING, Status.PAUSED)
    pause_metrics.record_app_transition("immich", Status.PAUSED, Status.RUNNING)
    pause_metrics.record_app_transition("immich", Status.RUNNING, Status.PAUSED)
    pause_metrics.record_pause_latency(100.0)
    pause_metrics.record_pause_latency(300.0)
    pause_metrics.record_unpause_latency(50.0)
    pause_metrics.record_psi_snapshot(2.5)
    pause_metrics.record_psi_snapshot(11.0)

    await telemetry.send_telemetry()

    body = mock_call_freeshard_controller.await_args_list[0].kwargs["body"]
    tel = Telemetry.model_validate(json.loads(body.decode()))
    assert tel.pause_tier is not None
    assert tel.pause_tier.transitions["immich"]["running_to_paused"] == 2
    assert tel.pause_tier.transitions["immich"]["paused_to_running"] == 1
    assert tel.pause_tier.pause_latency_ms_p50 in (100.0, 300.0)
    assert tel.pause_tier.unpause_latency_ms_p50 == 50.0
    assert tel.pause_tier.psi_some_avg10_snapshots == [2.5, 11.0]

    # accumulators reset after a successful send
    assert pause_metrics.app_transitions == {}
    assert pause_metrics.pause_latencies_ms == []
    assert pause_metrics.psi_snapshots == []


@patch("shard_core.service.telemetry.call_freeshard_controller", new_callable=AsyncMock)
async def test_telemetry_without_pause_activity_omits_pause_tier(
    mock_call_freeshard_controller: AsyncMock, app_client
):
    from shard_core.service import pause_metrics

    pause_metrics.reset()
    await telemetry.record_request("arg")
    await telemetry.send_telemetry()

    body = mock_call_freeshard_controller.await_args_list[0].kwargs["body"]
    tel = Telemetry.model_validate(json.loads(body.decode()))
    assert tel.pause_tier is None


def test_percentile_rejects_out_of_range_fraction():
    import pytest

    with pytest.raises(ValueError):
        telemetry._percentile([1.0, 2.0], 95)
    with pytest.raises(ValueError):
        telemetry._percentile([1.0, 2.0], -0.1)
    assert telemetry._percentile([1.0, 2.0, 3.0], 0.5) == 2.0
