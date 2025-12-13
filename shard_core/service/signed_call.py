import asyncio
import logging

import requests
from http_message_signatures import algorithms
from requests_http_signature import HTTPSignatureAuth

from shard_core.data_model.identity import Identity
from shard_core.service import identity as identity_service

log = logging.getLogger(__name__)


async def signed_request(
    *args, identity: Identity = None, **kwargs
) -> requests.Response:
    auth = get_signature_auth(identity)
    response = await asyncio.to_thread(requests.request, *args, auth=auth, **kwargs)
    return response


def get_signature_auth(identity: Identity = None):
    identity = identity or identity_service.get_default_identity()
    return HTTPSignatureAuth(
        signature_algorithm=algorithms.RSA_PSS_SHA512,
        key_id=identity.short_id,
        key=identity.private_key.encode(),
    )
