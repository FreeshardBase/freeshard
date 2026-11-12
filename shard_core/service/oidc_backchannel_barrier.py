"""Fail-closed barrier that holds HTTP traffic to an app while it still owes
an OIDC back-channel logout.

shard_core sits in the wake path: /internal/auth (web/internal/auth.py) is
the forwardAuth endpoint Traefik calls for every request to an app, and
on_request_to_app -- fired from there -- is what starts a stopped app. That
makes logout-before-serve enforceable rather than hoped for. While an app
has an undelivered logout, its traffic is answered with a 503, which renders
the same auto-reloading "Starting..." splash a cold app already shows
(web/internal/app_error.py maps 503 through neither the 401 nor the 500
branch, so do_reload stays True). Once the logout lands, the app is released.

Only HTTP is gated. MQTT rides a Traefik TCP router with no middleware, so
it bypasses this barrier entirely.

The set of app names with an undelivered logout is kept in process and never
read from the database on the request path -- #89: per-request DB lookups in
the auth endpoint exhausted the pool under bursts. It is rebuilt from the
outbox at boot and whenever the outbox changes (on_backchannel_outbox_update),
the same cache-plus-signal-invalidation pattern the auth endpoint already
uses for _app_cache / _identity_cache. The request-path cost on the normal,
empty-set case is one membership test.

If an app's logout endpoint is genuinely broken, holding would strand that
app for everyone. The hold is therefore bounded by BARRIER_TIMEOUT_SECONDS:
past the deadline the barrier fails OPEN with a loud log, trading the logout
guarantee for availability rather than bricking the app until an operator
intervenes.
"""

import asyncio
import logging
import time

from fastapi import HTTPException, status

from shard_core.database import oidc as db_oidc
from shard_core.database.connection import db_conn
from shard_core.service import oidc_backchannel_logout
from shard_core.util import signals

log = logging.getLogger(__name__)

BARRIER_TIMEOUT_SECONDS = 60

_pending_apps: set[str] = set()
_locks: dict[str, asyncio.Lock] = {}
_hold_since: dict[str, float] = {}
_failed_open: set[str] = set()


async def rebuild_pending_apps() -> None:
    """Replace the in-process pending set with the apps that currently have
    an undelivered logout in the outbox. Must be called at boot and after
    every outbox change; it is what keeps the request-path membership test
    truthful without the request path touching the database."""
    global _pending_apps
    async with db_conn() as conn:
        apps = await db_oidc.get_apps_with_pending_backchannel_logout(conn)
    _pending_apps = set(apps)
    for app_name in _hold_since.keys() - _pending_apps:
        _hold_since.pop(app_name, None)
        _failed_open.discard(app_name)


@signals.on_backchannel_outbox_update.connect
async def _rebuild_on_outbox_update(_):
    await rebuild_pending_apps()


def _lock_for(app_name: str) -> asyncio.Lock:
    lock = _locks.get(app_name)
    if lock is None:
        lock = _locks[app_name] = asyncio.Lock()
    return lock


async def enforce(app_name: str) -> None:
    """Hold traffic to an app that still owes a back-channel logout.

    Raises HTTPException(503) while the logout is undelivered and the
    fail-open deadline has not passed. Returns -- letting the request through
    -- when the app owes no logout, when delivery completes, or when the
    deadline has passed and the barrier fails open.

    Single-flight: concurrent callers for the same app serialize on one lock,
    so a waking app hit by dozens of requests drives one delivery attempt,
    not dozens.
    """
    if app_name not in _pending_apps:
        return

    started = _hold_since.setdefault(app_name, time.monotonic())
    if time.monotonic() - started >= BARRIER_TIMEOUT_SECONDS:
        if app_name not in _failed_open:
            _failed_open.add(app_name)
            log.error(
                "back-channel logout to app %s still undelivered after %ds; "
                "failing OPEN and serving traffic without it",
                app_name,
                BARRIER_TIMEOUT_SECONDS,
            )
        return

    async with _lock_for(app_name):
        if app_name not in _pending_apps:
            return
        try:
            await oidc_backchannel_logout.drain_due_outbox()
        except Exception:
            log.exception("drain during logout barrier for app %s failed", app_name)
        if app_name not in _pending_apps:
            return

    raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE)
