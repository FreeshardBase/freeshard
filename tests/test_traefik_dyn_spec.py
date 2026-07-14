import shutil
from pathlib import Path

import pytest
import yaml

from shard_core.data_model.app_meta import Status
from shard_core.database.connection import db_conn
from shard_core.database import installed_apps as db_installed_apps
from shard_core.service.app_installation.util import write_traefik_dyn_config
from shard_core.service.app_tools import get_installed_apps_path
from shard_core.settings import settings

pytestmark = pytest.mark.asyncio


def _read_traefik_dyn() -> dict:
    with open(
        Path(settings().path_root) / "core" / "traefik_dyn" / "traefik_dyn.yml", "r"
    ) as f:
        return yaml.safe_load(f)


@pytest.mark.parametrize("status", [Status.UNINSTALLATION_QUEUED, Status.UNINSTALLING])
async def test_app_being_uninstalled_gets_no_router(api_client, status):
    async with db_conn() as conn:
        await db_installed_apps.update_status(conn, "filebrowser", status)
    shutil.rmtree(get_installed_apps_path() / "filebrowser")

    await write_traefik_dyn_config()

    output = _read_traefik_dyn()
    assert "filebrowser_http" not in output["http"]["routers"]
    assert "filebrowser_http" not in output["http"]["services"]


async def test_template_is_written(api_client):
    with open(
        Path(settings().path_root) / "core" / "traefik_dyn" / "traefik_dyn.yml", "r"
    ) as f:
        output = yaml.safe_load(f)
        out_middlewares: dict = output["http"]["middlewares"]

        assert set(out_middlewares.keys()) == {
            "app-error",
            "auth",
            "strip",
            "auth-public",
            "auth-private",
            "auth-management",
        }
        assert "authResponseHeadersRegex" in out_middlewares["auth"]["forwardAuth"]

        out_services_http: dict = output["http"]["services"]
        assert set(out_services_http.keys()) == {
            "shard_core",
            "web-terminal",
            "filebrowser_http",
            "paperless-ngx_http",
            "immich_http",
        }
        assert out_services_http["filebrowser_http"]["loadBalancer"]["servers"] == [
            {"url": "http://filebrowser:80"}
        ]

        out_routers_http: dict = output["http"]["routers"]
        assert set(out_routers_http.keys()) == {
            "shard_core_private",
            "shard_core_public",
            "shard_core_management",
            "web-terminal",
            "traefik",
            "filebrowser_http",
            "paperless-ngx_http",
            "immich_http",
        }
        assert out_routers_http["filebrowser_http"]["service"] == "filebrowser_http"
