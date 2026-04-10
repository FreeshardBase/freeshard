import time
from datetime import datetime, timezone
from typing import Optional

from shard_core.database.connection import db_conn
from shard_core.database import installed_apps as db_installed_apps
from shard_core.data_model.app_meta import InstalledApp


async def test_app_last_access_is_set(api_client):
    assert await _get_last_access_time_delta("filebrowser") is None

    response = await api_client.get(
        "internal/auth",
        headers={
            "X-Forwarded-Host": "filebrowser.myshard.org",
            "X-Forwarded-Uri": "/share/foo",
        },
    )
    response.raise_for_status()

    assert await _get_last_access_time_delta("filebrowser") < 3


async def test_app_last_access_is_debounced(api_client):
    await api_client.get(
        "internal/auth",
        headers={
            "X-Forwarded-Host": "filebrowser.myshard.org",
            "X-Forwarded-Uri": "/share/foo",
        },
    )

    assert await _get_last_access_time_delta("filebrowser") < 3
    last_access = await _get_last_access_time("filebrowser")

    time.sleep(0.1)
    await api_client.get(
        "internal/auth",
        headers={
            "X-Forwarded-Host": "filebrowser.myshard.org",
            "X-Forwarded-Uri": "/share/foo",
        },
    )

    assert await _get_last_access_time("filebrowser") == last_access

    time.sleep(3)
    await api_client.get(
        "internal/auth",
        headers={
            "X-Forwarded-Host": "filebrowser.myshard.org",
            "X-Forwarded-Uri": "/share/foo",
        },
    )

    assert await _get_last_access_time_delta("filebrowser") < 3
    assert await _get_last_access_time("filebrowser") != last_access


async def _get_last_access_time_delta(app_name: str) -> Optional[float]:
    last_access = await _get_last_access_time(app_name)
    if last_access:
        now = datetime.now(timezone.utc)
        # Ensure both are timezone-aware for comparison
        if last_access.tzinfo is None:
            last_access = last_access.replace(tzinfo=timezone.utc)
        delta = now - last_access
        return delta.total_seconds()
    else:
        return None


async def _get_last_access_time(app_name: str) -> Optional[datetime]:
    async with db_conn() as conn:
        row = await db_installed_apps.get_by_name(conn, app_name)
    app = InstalledApp(**row)
    return app.last_access
