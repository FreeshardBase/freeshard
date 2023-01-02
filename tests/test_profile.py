from portal_core.model.profile import Profile
from tests import conftest


def test_profile(api_client, management_api_mock):
	response = api_client.get('public/meta/profile')
	response.raise_for_status()
	assert len(management_api_mock.calls) == 1
	assert Profile.parse_obj(response.json()) == conftest.mock_profile
