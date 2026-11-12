"""Fail-closed barrier that holds HTTP traffic to an app while it still owes
an OIDC back-channel logout, so an un-paired device is never served ahead of
its own logout. Held traffic gets a 503, which the app-error splash renders
as the auto-reloading wake-up page; once the logout lands, the app is
released.

Only HTTP is gated. MQTT rides a Traefik TCP router with no middleware, so it
bypasses this barrier entirely.

The set of app names with an undelivered logout is kept in process and never
queried from the database on the request path. It is rebuilt from the outbox
at boot and on on_backchannel_outbox_update.

The hold is bounded by BARRIER_TIMEOUT_SECONDS: past the deadline the barrier
fails open and serves traffic, logging at error.
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
_rebuild_lock = asyncio.Lock()


async def rebuild_pending_apps() -> None:
    """Replace the in-process pending set with the apps that currently have
    an undelivered logout in the outbox. Must be called at boot and after
    every outbox change; it is what keeps the request-path membership test
    truthful without the request path touching the database.

    Serialized on _rebuild_lock: the set gates auth decisions, and the many
    uncoordinated triggers (per-request drains, on_apps_update, the periodic
    backstop, un-pair) could otherwise let a rebuild reading older state
    overwrite one reading newer state."""
    global _pending_apps
    async with _rebuild_lock:
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


async def enforce(app_name: str, app_running: bool) -> None:
    """Hold traffic to an app that still owes a back-channel logout.

    Raises HTTPException(503) while the logout is undelivered and the
    fail-open deadline has not passed. Returns -- letting the request through
    -- when the app owes no logout, when delivery completes, or when the
    deadline has passed and the barrier fails open.

    The fail-open deadline only runs while app_running is True: the deadline
    bounds how long a reachable-but-broken logout endpoint may block the app,
    not how long a stopped app takes to wake and become deliverable.

    Single-flight: concurrent callers for the same app serialize on one lock,
    so a waking app hit by dozens of requests drives one delivery attempt,
    not dozens.
    """
    if app_name not in _pending_apps:
        return

    if app_running:
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
            await oidc_backchannel_logout.drain_due_outbox(app_name)
        except Exception:
            log.exception("drain during logout barrier for app %s failed", app_name)
        if app_name not in _pending_apps:
            return

    raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE)
