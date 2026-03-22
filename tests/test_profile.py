from httpx import AsyncClient

from shard_core.data_model.profile import Profile
from tests import conftest


async def test_profile(requests_mock, app_client: AsyncClient):
    response = await app_client.get("protected/management/profile")
    response.raise_for_status()
    assert Profile.model_validate(response.json()) == Profile.from_shard(
        conftest.mock_shard
    )
