from httpx import AsyncClient

from portal_core.model.profile import Profile
from tests import conftest


async def test_profile(requests_mock, api_client: AsyncClient):
	response = await api_client.get('protected/management/profile')
	response.raise_for_status()
	assert len(requests_mock.calls) == 2  # 1 during app startup, 1 during test
	assert Profile.parse_obj(response.json()) == conftest.mock_profile
