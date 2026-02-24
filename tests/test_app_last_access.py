import time
from datetime import datetime
from typing import Optional

from shard_core.database.connection import db_conn
from shard_core.database import installed_apps as installed_apps_db
from shard_core.data_model.app_meta import InstalledApp
from tests.conftest import requires_test_env


@requires_test_env("full")
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


@requires_test_env("full")
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
        now = datetime.utcnow()
        delta = now - last_access
        return delta.total_seconds()
    else:
        return None


async def _get_last_access_time(app_name: str) -> Optional[datetime]:
    async with db_conn() as conn:
        app_row = await installed_apps_db.get_by_name(conn, app_name)
    app = InstalledApp(**app_row)
    return app.last_access
