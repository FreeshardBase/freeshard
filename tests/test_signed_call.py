import pytest
from common_py.crypto import PublicKey
from http_message_signatures import InvalidSignature

from portal_core.model.identity import Identity, OutputIdentity
from portal_core.model.profile import Profile
from tests import conftest
from tests.util import verify_signature_auth


def test_call_management_api_verified(management_api_mock, api_client):
	portal_identity = OutputIdentity(**api_client.get('public/meta/whoareyou').json())
	pubkey = PublicKey(portal_identity.public_key_pem)
	profile_response = api_client.get('protected/management/profile')
	profile_response.raise_for_status()
	assert Profile.parse_obj(profile_response.json()) == conftest.mock_profile

	v = verify_signature_auth(management_api_mock.calls[0].request, pubkey)
	assert portal_identity.id.startswith(v.parameters['keyid'])


def test_call_management_api_fail_verify(management_api_mock, api_client):
	profile_response = api_client.get('protected/management/profile')
	profile_response.raise_for_status()
	assert Profile.parse_obj(profile_response.json()) == conftest.mock_profile

	invalid_identity = Identity.create('invalid')
	with pytest.raises(InvalidSignature):
		verify_signature_auth(management_api_mock.calls[0].request, invalid_identity.public_key)
