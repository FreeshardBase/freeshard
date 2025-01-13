import asyncio
import logging

import requests
from http_message_signatures import algorithms
from requests_http_signature import HTTPSignatureAuth

from portal_core.model.identity import Identity
from portal_core.service import identity as identity_service

log = logging.getLogger(__name__)


async def signed_request(*args, identity: Identity = None, **kwargs) -> requests.Response:
	auth = get_signature_auth(identity)

	def do_request():
		return requests.request(*args, auth=auth, **kwargs)

	response = await asyncio.get_running_loop().run_in_executor(None, do_request)

	return response


def get_signature_auth(identity: Identity = None):
	identity = identity or identity_service.get_default_identity()
	return HTTPSignatureAuth(
		signature_algorithm=algorithms.RSA_PSS_SHA512,
		key_id=identity.short_id,
		key=identity.private_key.encode(),
	)
