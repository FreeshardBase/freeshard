"""Unit tests for the last-access read cache (app_meta.get_last_access).

The DB is mocked — these pin that the cache actually elides DB reads within its
TTL and re-reads once it expires, which is the whole point of the cache added in
#133 (keep the forwardAuth hot path off the DB).
"""

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from shard_core.data_model import app_meta
from tests.conftest import settings_override


@asynccontextmanager
async def _fake_conn():
    yield None


async def test_get_last_access_serves_repeat_reads_from_cache():
    app_meta._last_access_cache.clear()
    ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
    get_by_name = AsyncMock(return_value={"last_access": ts})
    with (
        settings_override({"apps": {"last_access": {"read_cache_ttl": 3600}}}),
        patch("shard_core.database.connection.db_conn", _fake_conn),
        patch("shard_core.database.installed_apps.get_by_name", get_by_name),
    ):
        first = await app_meta.get_last_access("foo")
        second = await app_meta.get_last_access("foo")

    assert first == ts
    assert second == ts
    assert get_by_name.call_count == 1  # second read served from cache


async def test_get_last_access_rereads_after_ttl_expiry():
    app_meta._last_access_cache.clear()
    get_by_name = AsyncMock(return_value={"last_access": None})
    with (
        settings_override({"apps": {"last_access": {"read_cache_ttl": 0}}}),
        patch("shard_core.database.connection.db_conn", _fake_conn),
        patch("shard_core.database.installed_apps.get_by_name", get_by_name),
    ):
        await app_meta.get_last_access("foo")
        await app_meta.get_last_access("foo")

    assert get_by_name.call_count == 2  # ttl=0 never serves from cache
