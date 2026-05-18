from pathlib import Path

import yaml

from shard_core.settings import settings


async def test_template_is_written(api_client):
    with open(
        Path(settings().path_root) / "core" / "traefik_dyn" / "traefik_dyn.yml", "r"
    ) as f:
        output = yaml.safe_load(f)
        out_middlewares: dict = output["http"]["middlewares"]

        assert set(out_middlewares.keys()) == {
            "app-error",
            "auth",
            "authelia-forwardauth",
            "strip",
            "auth-public",
            "auth-private",
            "auth-management",
        }
        assert "authResponseHeadersRegex" in out_middlewares["auth"]["forwardAuth"]
        assert out_middlewares["authelia-forwardauth"]["forwardAuth"]["address"] == "http://authelia:9091/api/authz/forward-auth"

        out_services_http: dict = output["http"]["services"]
        assert set(out_services_http.keys()) == {
            "shard_core",
            "web-terminal",
            "authelia",
            "filebrowser_http",
            "paperless-ngx_http",
            "immich_http",
        }
        assert out_services_http["filebrowser_http"]["loadBalancer"]["servers"] == [
            {"url": "http://filebrowser:80"}
        ]
        assert out_services_http["authelia"]["loadBalancer"]["servers"] == [{"url": "http://authelia:9091/"}]

        out_routers_http: dict = output["http"]["routers"]
        assert set(out_routers_http.keys()) == {
            "shard_core_private",
            "shard_core_public",
            "shard_core_management",
            "web-terminal",
            "traefik",
            "authelia",
            "filebrowser_http",
            "paperless-ngx_http",
            "immich_http",
        }
        assert out_routers_http["filebrowser_http"]["service"] == "filebrowser_http"
        assert out_routers_http["filebrowser_http"]["middlewares"] == [
            "app-error",
            "authelia-forwardauth",
        ]
