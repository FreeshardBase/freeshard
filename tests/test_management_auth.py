import pytest
from httpx import AsyncClient

from shard_core.database import database
from shard_core.service import freeshard_controller
from shard_core.service.freeshard_controller import (
    STORE_KEY_FREESHARD_CONTROLLER_SHARED_KEY,
)


async def test_refresh_shared_secret(app_client: AsyncClient, requests_mock):
    with pytest.raises(KeyError):
        await database.get_value(STORE_KEY_FREESHARD_CONTROLLER_SHARED_KEY)

    await freeshard_controller.refresh_shared_secret()

    assert await database.get_value(STORE_KEY_FREESHARD_CONTROLLER_SHARED_KEY)


async def test_auth_call_success_with_shared_secret(
    app_client: AsyncClient, requests_mock
):
    response = await app_client.get(
        "internal/authenticate_management",
        headers={"authorization": "foosecretbar"},
    )
    response.raise_for_status()


async def test_auth_call_fail_with_wrong_shared_secret(
    app_client: AsyncClient, requests_mock
):
    response = await app_client.get(
        "internal/authenticate_management", headers={"authorization": "failingSecret"}
    )
    assert response.status_code == 401
