import logging

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import Response
from pydantic import BaseModel

from shard_core.service import owner_email
from shard_core.util.misc import SlidingWindow

log = logging.getLogger(__name__)

# The token is opaque to everyone but the shard that minted it; anything far off
# its length is not a guess worth spending a rate-limit slot on.
_MAX_TOKEN_LENGTH = 512
_confirm_limit = SlidingWindow(limit=10, window=60)

router = APIRouter(
    prefix="/users",
)


class ConfirmEmailInput(BaseModel):
    token: str


@router.post(
    "/confirm-email",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def confirm_email(body: ConfirmEmailInput):
    """Promote the address the token belongs to.

    The only unauthenticated surface of the address flow, and the token is its
    only credential: compared in constant time against a stored digest, usable
    once, valid for an hour, and rate limited.

    A well-formed request always answers 204, whether or not the token matched.
    Anything else would let a caller probe for pending addresses.

    There is deliberately no GET: mail scanners and link prefetchers follow
    links, and a GET that mutates would burn the single-use token before the
    owner ever clicked. The mail points at the terminal UI
    (https://<shard-domain>/?confirm_email=<token>), which posts here.
    """
    if not body.token or len(body.token) > _MAX_TOKEN_LENGTH:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Malformed token.")
    if _confirm_limit.is_exceeded():
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS)
    await owner_email.confirm_email(body.token)
