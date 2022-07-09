import pytest
import responses
from http_message_signatures import algorithms, HTTPSignatureKeyResolver, InvalidSignature
from requests_http_signature import HTTPSignatureAuth

from portal_core.model.identity import Identity

management_api = 'https://management-mock'
config_override = {'management': {'api_url': management_api}}


@responses.activate
def test_call_management_api_verified(api_client):
	response_body = {'name': 'test'}
	responses.get(
		f'{management_api}/profile',
		json=response_body,
	)
	profile_response = api_client.get('public/meta/profile')
	assert profile_response.json() == response_body

	# attempt to verify the request that was just sent

	class KR(HTTPSignatureKeyResolver):
		def resolve_private_key(self, key_id: str):
			pass

		def resolve_public_key(self, key_id: str):
			whoareyou = api_client.get('public/meta/whoareyou')
			return whoareyou.json()['public_key_pem'].encode()

	HTTPSignatureAuth.verify(
		responses.calls[0].request,
		signature_algorithm=algorithms.RSA_PSS_SHA512,
		key_resolver=KR(),
	)


@responses.activate
def test_call_management_api_fail_verify(api_client):
	response_body = {'name': 'test'}
	responses.get(
		f'{management_api}/profile',
		json=response_body,
	)
	profile_response = api_client.get('public/meta/profile')
	assert profile_response.json() == response_body

	# attempt to verify the request that was just sent

	invalid_identity = Identity.create('invalid')

	class KR(HTTPSignatureKeyResolver):
		def resolve_private_key(self, key_id: str):
			pass

		def resolve_public_key(self, key_id: str):
			return invalid_identity.public_key_pem.encode()

	with pytest.raises(InvalidSignature):
		HTTPSignatureAuth.verify(
			responses.calls[0].request,
			signature_algorithm=algorithms.RSA_PSS_SHA512,
			key_resolver=KR(),
		)
