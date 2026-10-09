from types import SimpleNamespace
from unittest.mock import AsyncMock

from starlette import status

from shard_core.data_model.app_meta import AppMeta
from shard_core.service import app_tools
from shard_core.web.internal import app_error
from tests.util import install_app


def _meta(minimum_freeshard_version: str | None) -> AppMeta:
    return AppMeta(
        v="1.3",
        app_version="1.0.0",
        name="test",
        pretty_name="Test",
        icon="icon.svg",
        entrypoints=[],
        paths={},
        minimum_freeshard_version=minimum_freeshard_version,
    )


async def _splash_for(mocker, *, running_version: str, minimum: str, status_code: str):
    """Run get_splash_behaviour for an installed, size-compatible app whose
    container exists but is not running ("created", as after `up --no-start`),
    varying only the shard version, the app's requirement, and the HTTP status.
    """
    mocker.patch.object(app_error, "get_app_name", return_value="test")
    mocker.patch.object(app_error, "get_app_metadata", return_value=_meta(minimum))
    mocker.patch.object(app_error, "get_container_status", return_value="created")
    mocker.patch.object(app_error, "data_url", return_value="data:,")
    mocker.patch.object(
        app_error, "size_is_compatible", new=AsyncMock(return_value=True)
    )
    # Patch get_freeshard_version at its source module: app_error reaches it only
    # indirectly through freeshard_version_is_compatible, so patching it on
    # app_error would not take effect.
    mocker.patch.object(
        app_tools, "get_freeshard_version", return_value=running_version
    )
    mocker.patch.object(
        app_error.disk,
        "current_disk_usage",
        app_error.disk.DiskUsage(total_gb=10, free_gb=9, disk_space_low=False),
    )
    request = SimpleNamespace(path_params={"status": status_code})
    return await app_error.get_splash_behaviour(request)


async def test_splash_reports_shard_too_old(mocker):
    behaviour = await _splash_for(
        mocker, running_version="0.40.6", minimum="0.41.0", status_code="502"
    )
    assert behaviour.display_status == "Shard too old, need at least v0.41.0"
    assert behaviour.do_reload is False


async def test_splash_ok_when_version_compatible(mocker):
    behaviour = await _splash_for(
        mocker, running_version="0.41.0", minimum="0.41.0", status_code="502"
    )
    assert behaviour.display_status == "Unknown Status..."
    assert behaviour.do_reload is True


async def test_splash_error_status_overrides_version_message(mocker):
    # The version branch sets do_reload=False, but an explicit 500 still wins
    # on the display text (same precedence the portal-size branch has). Pin it
    # so a change to the ordering is noticed.
    behaviour = await _splash_for(
        mocker, running_version="0.40.6", minimum="0.41.0", status_code="500"
    )
    assert behaviour.display_status == "Error"
    assert behaviour.do_reload is False


async def test_status_404(api_client):
    await install_app(api_client, "mock_app")
    response = await api_client.get(
        "internal/app_error/404",
        headers={"host": "mock_app.myshard.org", "X-Forwarded-Uri": "/pub"},
    )
    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert "404" in response.text


async def test_status_500(api_client):
    await install_app(api_client, "mock_app")
    response = await api_client.get(
        "internal/app_error/500",
        headers={"host": "mock_app.myshard.org", "X-Forwarded-Uri": "/pub"},
    )
    assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    assert "500" in response.text
