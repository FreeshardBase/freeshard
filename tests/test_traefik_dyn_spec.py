import json
import logging
import shutil
from pathlib import Path

import pytest
import yaml

from shard_core.data_model.app_meta import InstallationReason, Status
from shard_core.database import installed_apps as db_installed_apps
from shard_core.database.connection import db_conn
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
            "strip-sundial",
            "redirect-sundial-slash",
            "auth-public",
            "auth-private",
            "auth-management",
        }
        assert "authResponseHeadersRegex" in out_middlewares["auth"]["forwardAuth"]
        assert out_middlewares["strip-sundial"]["stripPrefix"]["prefixes"] == [
            "/sundial"
        ]
        assert out_middlewares["redirect-sundial-slash"]["redirectRegex"] == {
            "regex": "^(https?://[^/]+)/sundial$",
            "replacement": "${1}/sundial/",
            "permanent": True,
        }

        out_services_http: dict = output["http"]["services"]
        assert set(out_services_http.keys()) == {
            "shard_core",
            "web-terminal",
            "sundial",
            "filebrowser_http",
            "paperless-ngx_http",
            "immich_http",
        }
        assert out_services_http["sundial"]["loadBalancer"]["servers"] == [
            {"url": "http://sundial:80/"}
        ]
        assert out_services_http["filebrowser_http"]["loadBalancer"]["servers"] == [
            {"url": "http://filebrowser:80"}
        ]

        out_routers_http: dict = output["http"]["routers"]
        assert set(out_routers_http.keys()) == {
            "shard_core_private",
            "shard_core_public",
            "shard_core_management",
            "web-terminal",
            "sundial",
            "traefik",
            "filebrowser_http",
            "paperless-ngx_http",
            "immich_http",
        }
        assert out_routers_http["filebrowser_http"]["service"] == "filebrowser_http"

        sundial_router = out_routers_http["sundial"]
        assert sundial_router["rule"] == "PathPrefix(`/sundial`)"
        assert sundial_router["service"] == "sundial"
        assert sundial_router["middlewares"] == [
            "redirect-sundial-slash",
            "strip-sundial",
        ]
        assert sundial_router["priority"] > out_routers_http["web-terminal"]["priority"]
        assert out_routers_http["web-terminal"]["rule"] == "PathPrefix(`/`)"


def _write_app_meta(app_name: str):
    app_path = get_installed_apps_path() / app_name
    app_path.mkdir(parents=True, exist_ok=True)
    (app_path / "app_meta.json").write_text(
        json.dumps(
            {
                "v": "1.0",
                "app_version": "0.1.0",
                "name": app_name,
                "pretty_name": app_name,
                "icon": "icon.svg",
                "entrypoints": [
                    {
                        "container_name": app_name,
                        "container_port": 80,
                        "entrypoint_port": "http",
                    }
                ],
                "paths": {"": {"access": "public"}},
            }
        )
    )


async def _add_app_to_db(app_name: str, status: Status):
    async with db_conn() as conn:
        await db_installed_apps.insert(
            conn,
            {
                "name": app_name,
                "installation_reason": InstallationReason.CUSTOM.value,
                "status": status.value,
                "last_access": None,
            },
        )


def _read_traefik_dyn_config() -> dict:
    with open(
        Path(settings().path_root) / "core" / "traefik_dyn" / "traefik_dyn.yml", "r"
    ) as f:
        return yaml.safe_load(f)


async def test_app_with_missing_metadata_is_skipped(app_client, memory_logger):
    _write_app_meta("healthy_app")
    await _add_app_to_db("healthy_app", Status.RUNNING)
    await _add_app_to_db("broken_app", Status.RUNNING)

    await write_traefik_dyn_config()

    routers = _read_traefik_dyn_config()["http"]["routers"]
    assert "healthy_app_http" in routers
    assert "broken_app_http" not in routers
    assert [
        r
        for r in memory_logger.records
        if r.levelno == logging.WARNING and "broken_app" in r.getMessage()
    ]


async def test_uninstalling_app_is_not_routed(app_client):
    _write_app_meta("uninstalling_app")
    await _add_app_to_db("uninstalling_app", Status.UNINSTALLING)

    await write_traefik_dyn_config()

    assert "uninstalling_app_http" not in _read_traefik_dyn_config()["http"]["routers"]
