from httpx import AsyncClient

from portal_core.model.profile import Profile
from tests import conftest


async def test_profile(api_client: AsyncClient, management_api_mock):
	response = await api_client.get('protected/management/profile')
	response.raise_for_status()
	assert len(management_api_mock.calls) == 1
	assert Profile.parse_obj(response.json()) == conftest.mock_profile
