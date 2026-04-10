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
