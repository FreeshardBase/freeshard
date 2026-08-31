import logging

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import Response
from pydantic import BaseModel, Field

from shard_core.service import owner_email
from shard_core.util.misc import SlidingWindow

log = logging.getLogger(__name__)

# Charged only when a token does not match, so a flood of guesses can never lock
# the owner out of the one route that produces a verified address. Against a
# 256-bit token the limit buys little anyway; it is here to keep the log and the
# database from being pumped for free.
_miss_limit = SlidingWindow(limit=20, window=60)

router = APIRouter(
    prefix="/users",
)


class ConfirmEmailInput(BaseModel):
    token: str = Field(min_length=1, max_length=512)


@router.post(
    "/confirm-email",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def confirm_email(body: ConfirmEmailInput):
    """Promote the address the token belongs to.

    The only unauthenticated surface of the address flow, and the token is its
    only credential: matched in constant time against a stored digest, spent in
    a single conditional UPDATE, and valid for an hour.

    A request carrying a plausible token always answers 204, whether or not it
    matched — anything else would let a caller probe for pending addresses. The
    429 a flood eventually earns is not such a probe: a guess misses whether or
    not an address is pending.

    There is deliberately no GET: mail scanners and link prefetchers follow
    links, and a GET that mutates would burn the single-use token before the
    owner ever clicked. The mail points at the terminal UI
    (https://<shard-domain>/?confirm_email=<token>), which posts here.
    """
    if await owner_email.confirm_email(body.token):
        log.info("confirmed a pending email address")
        return
    log.info("rejected an email confirmation token")
    if not _miss_limit.try_acquire():
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS)
