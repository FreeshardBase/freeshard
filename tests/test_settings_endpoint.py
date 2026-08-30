import pytest
from httpx import AsyncClient

from tests.conftest import settings_override

pytest_plugins = ("pytest_asyncio",)
pytestmark = pytest.mark.asyncio


async def test_reports_that_the_shard_can_send_mail(api_client: AsyncClient):
    response = await api_client.get("protected/settings")
    assert response.status_code == 200
    assert response.json()["email_enabled"] is True


async def test_reports_when_it_cannot(api_client: AsyncClient):
    with settings_override({"email": {"enabled": False}}):
        response = await api_client.get("protected/settings")
    assert response.status_code == 200
    assert response.json()["email_enabled"] is False


async def test_publishes_nothing_beyond_the_allowlist(api_client: AsyncClient):
    """The point of the endpoint is what it does *not* say.

    Settings holds the database password, the controller base URL and the
    management API URL. Asserting the exact key set means a field added
    elsewhere in the config cannot start being published here unnoticed —
    whoever adds one has to come here and say so.
    """
    body = (await api_client.get("protected/settings")).json()
    assert set(body) == {"email_enabled"}
