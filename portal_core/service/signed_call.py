import requests
from http_message_signatures import algorithms
from requests_http_signature import HTTPSignatureAuth

from portal_core.model.identity import Identity
from portal_core.service import identity as identity_service


def signed_request(*args, identity: Identity = None, **kwargs) -> requests.Response:
	identity = identity or identity_service.get_default_identity()
	auth = HTTPSignatureAuth(
		signature_algorithm=algorithms.RSA_PSS_SHA512,
		key_id=identity.short_id,
		key=identity.private_key.encode(),
	)
	return requests.request(*args, auth=auth, **kwargs)
