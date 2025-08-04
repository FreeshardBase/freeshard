import pytest
from httpx import AsyncClient

from shard_core.database import database
from shard_core.service import management
from shard_core.service.management import STORE_KEY_MANAGEMENT_SHARED_KEY
from tests.conftest import requires_test_env


@requires_test_env("full")
async def test_refresh_shared_secret(api_client: AsyncClient, requests_mock):
    with pytest.raises(KeyError):
        database.get_value(STORE_KEY_MANAGEMENT_SHARED_KEY)

    await management.refresh_shared_secret()

    assert database.get_value(STORE_KEY_MANAGEMENT_SHARED_KEY)


@requires_test_env("full")
async def test_auth_call_success_with_empty_shared_secret(
    api_client: AsyncClient, requests_mock
):
    response = await api_client.get(
        "internal/authenticate_management",
        headers={"authorization": "constantSharedSecret"},
    )
    response.raise_for_status()


@requires_test_env("full")
async def test_auth_call_success_with_wrong_shared_secret(
    api_client: AsyncClient, requests_mock
):
    database.set_value(STORE_KEY_MANAGEMENT_SHARED_KEY, "wrongSecret")
    response = await api_client.get(
        "internal/authenticate_management",
        headers={"authorization": "constantSharedSecret"},
    )
    response.raise_for_status()


@requires_test_env("full")
async def test_auth_call_fail_with_empty_shared_secret(
    api_client: AsyncClient, requests_mock
):
    response = await api_client.get(
        "internal/authenticate_management", headers={"authorization": "failingSecret"}
    )
    assert response.status_code == 401


@requires_test_env("full")
async def test_auth_call_fail_with_wrong_shared_secret(
    api_client: AsyncClient, requests_mock
):
    database.set_value(STORE_KEY_MANAGEMENT_SHARED_KEY, "wrongSecret")
    response = await api_client.get(
        "internal/authenticate_management", headers={"authorization": "failingSecret"}
    )
    assert response.status_code == 401
