import json

from shard_core.data_model.backend.telemetry_model import Telemetry
from shard_core.service import telemetry
from unittest.mock import AsyncMock, patch
from fastapi import status

from tests import util
from tests.conftest import requires_test_env
from tests.util import pair_new_terminal
import gconf


@requires_test_env("full")
async def test_telemetry_recording(api_client):
    app_name = "mock_app"
    await util.install_app(api_client, app_name)

    await pair_new_terminal(api_client)

    assert (
        await api_client.get(
            "internal/auth",
            headers={
                "X-Forwarded-Host": f"{app_name}.myshard.org",
                "X-Forwarded-Uri": "/private1",
            },
        )
    ).status_code == status.HTTP_200_OK

    # One request during pairing, one because of the explicit GET
    assert telemetry.no_of_requests == 2


@requires_test_env("full")
@patch("shard_core.service.telemetry.call_freeshard_controller", new_callable=AsyncMock)
async def test_telemetry_sending(mock_call_freeshard_controller: AsyncMock, api_client):
    for i in range(3):
        telemetry.record_request("arg")
    await telemetry.send_telemetry()

    assert mock_call_freeshard_controller.called
    body = mock_call_freeshard_controller.await_args_list[0].kwargs["body"]
    tel = Telemetry.validate(json.loads(body.decode()))
    assert tel.no_of_requests == 3


@requires_test_env("full")
async def test_telemetry_sending_failure(api_client):
    with gconf.override_conf(
        {"freeshard_controller": {"base_url": "https://non-existing.com"}}
    ):
        telemetry.record_request("arg")
        await telemetry.send_telemetry()


@requires_test_env("full")
@patch("shard_core.service.telemetry.call_freeshard_controller", new_callable=AsyncMock)
async def test_telemetry_disabled(
    mock_call_freeshard_controller: AsyncMock, api_client
):
    with gconf.override_conf({"telemetry": {"enabled": False}}):
        telemetry.record_request("arg")
        await telemetry.send_telemetry()

        assert telemetry.no_of_requests == 0
        assert not mock_call_freeshard_controller.called
