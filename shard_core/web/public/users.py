import logging
from typing import Literal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from shard_core.service import owner_email
from shard_core.service.owner_email import TokenStatus
from shard_core.util.misc import SlidingWindow

log = logging.getLogger(__name__)

# Charged on anything short of CONFIRMED. CONFIRMED alone is exempt: claiming
# a real token clears its stored digest, so it can happen at most once and
# can't be replayed. EXPIRED has no such limit — nothing purges an expired
# row, so a once-real token stays matchable indefinitely and would otherwise
# be a free, unthrottled replay even though it can never confirm anything.
_miss_limit = SlidingWindow(limit=20, window=60)

router = APIRouter(
    prefix="/users",
)


class ConfirmEmailInput(BaseModel):
    token: str = Field(min_length=1, max_length=512)


class ConfirmEmailResult(BaseModel):
    status: Literal["unknown", "expired", "confirmed"]
    email: str | None = None


@router.post("/confirm-email")
async def confirm_email(body: ConfirmEmailInput) -> ConfirmEmailResult:
    """Report which of three outcomes redeeming the token produced.

    The only unauthenticated surface of the address flow, and the token is its
    only credential: matched in constant time against a stored digest, spent in
    a single conditional UPDATE, and valid for an hour.

    UNKNOWN and EXPIRED are both safe to return to an unauthenticated caller —
    see TokenStatus for why distinguishing them costs a guesser nothing. Both
    are charged against the miss limiter below, though: that secrecy argument
    is about what a response may *say*, not about how often it may be asked
    for, and only CONFIRMED is naturally rate-limited by being single-use.

    There is deliberately no GET: mail scanners and link prefetchers follow
    links, and a GET that mutates would burn the single-use token before the
    owner ever clicked. The mail points at the terminal UI
    (https://<shard-domain>/?confirm_email=<token>), which posts here.
    """
    result = await owner_email.confirm_email(body.token)
    if result.status == TokenStatus.CONFIRMED:
        log.info("confirmed a pending email address")
    else:
        log.info(f"rejected an email confirmation token ({result.status.value})")
        if not _miss_limit.try_acquire():
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS)
    return ConfirmEmailResult(status=result.status.value, email=result.email)
