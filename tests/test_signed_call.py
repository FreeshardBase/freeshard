from time import sleep

import pytest
import responses
from http_message_signatures import algorithms, HTTPSignatureKeyResolver, InvalidSignature
from requests_http_signature import HTTPSignatureAuth

from portal_core.model.identity import Identity

management_api = 'https://management-mock'
config_override = {'management': {'api_url': management_api}}


@pytest.fixture
def management_api_mock():
	with responses.RequestsMock() as rsps:
		rsps.get(
			f'{management_api}/profile',
			json={'name': 'test'},
		)
		rsps.add_passthru('')
		yield rsps


def test_call_management_api_verified(api_client, management_api_mock):
	profile_response = api_client.get('public/meta/profile')
	assert profile_response.json()['name'] == 'test'

	# attempt to verify the request that was just sent
	class KR(HTTPSignatureKeyResolver):
		def resolve_private_key(self, key_id: str):
			pass

		def resolve_public_key(self, key_id: str):
			whoareyou = api_client.get('public/meta/whoareyou')
			return whoareyou.json()['public_key_pem'].encode()

	HTTPSignatureAuth.verify(
		management_api_mock.calls[0].request,
		signature_algorithm=algorithms.RSA_PSS_SHA512,
		key_resolver=KR(),
	)


def test_call_management_api_fail_verify(api_client, management_api_mock):
	profile_response = api_client.get('public/meta/profile')
	assert profile_response.json()['name'] == 'test'

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
