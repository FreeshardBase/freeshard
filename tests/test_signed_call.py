import pytest
from common_py.crypto import PublicKey
from http_message_signatures import algorithms, HTTPSignatureKeyResolver, InvalidSignature
from requests_http_signature import HTTPSignatureAuth

from portal_core.model.identity import Identity


def test_call_management_api_verified(management_api_mock, api_client):
	portal_id = api_client.get('public/meta/whoareyou').json()['id']
	profile_response = api_client.get('public/meta/profile')
	assert profile_response.json()['owner'] == 'test owner'

	# attempt to verify the request that was just sent
	class KR(HTTPSignatureKeyResolver):
		def resolve_private_key(self, key_id: str):
			pass

		def resolve_public_key(self, key_id: str):
			assert portal_id.startswith(key_id)
			whoareyou = api_client.get('public/meta/whoareyou')
			pubkey = PublicKey(whoareyou.json()['public_key_pem'])
			assert pubkey.to_hash_id().startswith(key_id)
			return whoareyou.json()['public_key_pem'].encode()

	v = HTTPSignatureAuth.verify(
		management_api_mock.calls[0].request,
		signature_algorithm=algorithms.RSA_PSS_SHA512,
		key_resolver=KR(),
	)
	assert portal_id.startswith(v.parameters['keyid'])


def test_call_management_api_fail_verify(management_api_mock, api_client):
	profile_response = api_client.get('public/meta/profile')
	assert profile_response.json()['owner'] == 'test owner'

	# attempt to verify the request that was just sent
	invalid_identity = Identity.create('invalid')

	class KR(HTTPSignatureKeyResolver):
		def resolve_private_key(self, key_id: str):
			pass

		def resolve_public_key(self, key_id: str):
			return invalid_identity.public_key_pem.encode()

	with pytest.raises(InvalidSignature):
		HTTPSignatureAuth.verify(
			management_api_mock.calls[0].request,
			signature_algorithm=algorithms.RSA_PSS_SHA512,
			key_resolver=KR(),
		)
