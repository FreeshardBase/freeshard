import base64
import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Optional

import docker
import jinja2
from docker import errors as docker_errors
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from shard_core.service import disk
from shard_core.service.app_tools import (
    get_app_metadata,
    MetadataNotFound,
    get_installed_apps_path,
    size_is_compatible,
)

log = logging.getLogger(__name__)

router = APIRouter()


@router.get("/app_error/{status}")
async def app_error(status: int, request: Request):
    behaviour = await get_splash_behaviour(request)
    return render_splash_response(behaviour, status)


class SplashBehaviour(BaseModel):
    app_name: str
    status_code: int
    container_status: str
    icon_data: str
    display_status: str
    do_reload: bool
    upstream_json: Optional[str] = None


def build_upstream_json(status: int, content_type: Optional[str], body: str) -> str:
    """Safely encode upstream response data for embedding in a <script> tag.

    The result is a JSON string where '</script>' sequences are escaped so
    they cannot prematurely close the surrounding <script> tag.
    """
    data = {
        "status": status,
        "content_type": content_type,
        "body": body,
    }
    json_str = json.dumps(data, ensure_ascii=False)
    # Prevent '</script>' injection by escaping the forward slash after '<'
    json_str = json_str.replace("</", "<\\/")
    return json_str


def render_splash_response(
    behaviour: SplashBehaviour, status_code: int
) -> HTMLResponse:
    template = get_template_splash()
    return HTMLResponse(
        content=template.render(**behaviour.model_dump()), status_code=status_code
    )


async def get_splash_behaviour(
    request: Request, upstream_json: Optional[str] = None
) -> SplashBehaviour:
    # todo: add special splash screen for app that is not size compatible
    status_code = int(request.path_params["status"])
    app_name = get_app_name(request)
    app_meta = get_app_metadata(app_name)
    container_status = get_container_status(app_name)

    behaviour = SplashBehaviour(
        status_code=status_code,
        app_name=app_name,
        container_status=container_status,
        icon_data=data_url(app_name),
        display_status="Unknown Status...",
        do_reload=True,
        upstream_json=upstream_json,
    )
    if disk.current_disk_usage.disk_space_low:
        behaviour.display_status = "Low Disk Space"
        behaviour.do_reload = False
    if not await size_is_compatible(app_meta.minimum_portal_size):
        display_size = app_meta.minimum_portal_size.value.upper()
        behaviour.display_status = f"VM too small, need at least {display_size}"
        behaviour.do_reload = False
    if status_code == 401:
        behaviour.display_status = "Access Denied"
        behaviour.do_reload = False
    elif status_code == 500:
        behaviour.display_status = "Error"
    elif container_status == "running":
        behaviour.display_status = "Starting..."
    elif container_status == "unknown":
        behaviour.display_status = "Initializing..."

    return behaviour


async def make_splash_behaviour_for_proxy(
    app_name: str,
    status_code: int,
    container_status: str,
    upstream_json: Optional[str],
) -> SplashBehaviour:
    """Build SplashBehaviour for use by the app proxy (no request path params needed)."""
    try:
        app_meta = get_app_metadata(app_name)
        icon = data_url(app_name)
        size_ok = await size_is_compatible(app_meta.minimum_portal_size)
        display_size = app_meta.minimum_portal_size.value.upper()
    except MetadataNotFound:
        app_meta = None
        icon = PLACEHOLDER_DATA
        size_ok = True
        display_size = None

    behaviour = SplashBehaviour(
        status_code=status_code,
        app_name=app_name,
        container_status=container_status,
        icon_data=icon,
        display_status="Unknown Status...",
        do_reload=True,
        upstream_json=upstream_json,
    )

    if disk.current_disk_usage.disk_space_low:
        behaviour.display_status = "Low Disk Space"
        behaviour.do_reload = False
    elif app_meta and not size_ok:
        behaviour.display_status = f"VM too small, need at least {display_size}"
        behaviour.do_reload = False
    elif status_code == 401:
        behaviour.display_status = "Access Denied"
        behaviour.do_reload = False
    elif status_code == 500:
        behaviour.display_status = "Error"
    elif container_status == "running":
        behaviour.display_status = "Starting..."
    elif container_status == "unknown":
        behaviour.display_status = "Initializing..."

    return behaviour


def get_container_status(app_name):
    docker_client = get_docker_client()
    try:
        status = docker_client.containers.get(app_name).status
    except docker_errors.NotFound:
        status = "unknown"
    return status


def get_app_name(request):
    host_header: str = request.headers.get("host")
    app_name = host_header.split(".")[0]
    return app_name


@lru_cache()
def get_docker_client():
    return docker.from_env()


@lru_cache()
def get_template_splash():
    with open(Path.cwd() / "data" / "splash.html", "r") as f:
        template = jinja2.Template(f.read())
    return template


@lru_cache(maxsize=16)
def data_url(app_name):
    try:
        app_meta = get_app_metadata(app_name)
    except MetadataNotFound:
        return PLACEHOLDER_DATA
    icon_file = get_installed_apps_path() / app_name / app_meta.icon

    b64 = base64.b64encode(icon_file.read_bytes()).decode()
    image_type = icon_file.suffix[1:]
    if image_type == "svg":
        image_type = "svg+xml"
    return f"data:image/{image_type};base64,{b64}"


PLACEHOLDER_DATA = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAgAAAAIACAYAAAD0eNT6AAAzNUlEQVR42u3dC6xlV33f8f9+3PedGXvGY4eR3zNm7IEQjKZJsVzVSQhErRIUuUAU0gQWPahRRZO0CVGlpq2ES1xUY4hJQggEhySgOAkQXBeHhIbEUDsxaezysp36D66HR0ttMI+Uh5mp9vScyZkzd+7d++xzzn/91/pe6Uixwnx091r/tX/rnv85a8tznnPd8nOec92S9Php/v3QWcbDw8PDw8Nz4DE4eHh4eHh4GXoMDh4eHh4eXoYeg4OHh4eHh5ehx+Dg4eHh4eHhMTh4eHh4eHiEP4ODh4eHh4dH+DPYeHh4eHh4hD+DjYeHh4eHR/jj4eHh4eHhEf54eHh4eHh4hD8eHh4eHh5eRB6Dg4eHh4eHl6HH4ODh4eHh4WXoMTh4eHh4eHgZegwOHh4eHh4eHoODh4eHh4dH+DM4eHh4eHh4hD+DjYeHh4eHR/gz2Hh4eHh4eIQ/Hh4eHh4enhOPwcHDw8PDw8vQY3Dw8PDw8PAy9BgcPDw8PDy8DD0GBw8PDw8PD4/BwcPDw8PDI/wZHDw8PDw8PMKfwcbDw8PDwyP8GWw8PDw8PDzCHw8PDw8PD4/wx8PDw8PDwyP88fDw8PDw8CLyGBw8PDw8PLwMPQYHDw8PDw8vQ4/BwcPDw8PDy9BjcPDw8PDw8PAYHDw8PDw8PMKfwcHDw8PDwyP8GWw8PDw8PDzCn8HGw8PDw8Mj/PHw8PDw8PCceAwOHh4eHh5ehh6Dg4eHh4eHl6HH4ODh4eHh4WXoMTh4eHh4eHh4DA4eHh4eHl4O3v8DyOlLVWYaMhkAAAAASUVORK5CYII="  # noqa: E501
