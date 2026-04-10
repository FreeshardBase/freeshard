import logging
import sys
from contextlib import asynccontextmanager
from importlib.metadata import metadata
from pathlib import Path
from typing import List

import jinja2
from fastapi import FastAPI
from pydantic import ValidationError
from requests import ConnectionError, HTTPError

from .database import database
from .database.connection import db_conn
from .database import terminals as db_terminals
from .service import (
    app_installation,
    identity,
    app_lifecycle,
    peer,
    app_usage_reporting,
    websocket,
    migration,
    portal_controller,
    backup,
    disk,
    telemetry,
)
from .service.app_installation.util import (
    write_traefik_dyn_config,
    render_all_docker_compose_templates,
)
from .service.app_tools import (
    docker_stop_all_apps,
    docker_shutdown_all_apps,
    scheduled_docker_prune_images,
)
from .service.backup import start_backup
from .service.pairing import make_pairing_code
from .settings import settings
from .util.async_util import PeriodicTask, BackgroundTask, CronTask
from .web import internal, public, protected, management

log = logging.getLogger(__name__)


def create_app():
    configure_logging()

    _copy_traefik_static_config()

    app_meta = metadata("shard_core")
    app = FastAPI(
        title="Shard Core",
        description=app_meta["summary"],
        version=app_meta["version"],
        redoc_url="/redoc",
        lifespan=lifespan,
    )
    app.include_router(internal.router)
    app.include_router(public.router)
    app.include_router(protected.router)
    app.include_router(management.router)

    return app


def configure_logging():
    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    for module, level in settings().log.levels.items():  # type: str, str
        logger = logging.getLogger() if module == "root" else logging.getLogger(module)
        logger.setLevel(getattr(logging, level.upper()))
        log.info(f"set logger for {module} to {level.upper()}")


@asynccontextmanager
async def lifespan(_):
    await database.init_database()
    await identity.init_default_identity()

    await write_traefik_dyn_config()
    await render_all_docker_compose_templates()
    await app_installation.login_docker_registries()
    await migration.migrate()
    await app_installation.refresh_init_apps()
    await backup.ensure_backup_passphrase()
    try:
        await portal_controller.refresh_profile()
    except (ConnectionError, HTTPError, ValidationError) as e:
        log.error(f"could not refresh profile: {e}")

    background_tasks = _make_background_tasks()
    for t in background_tasks:
        t.start()

    log.info("Startup complete")
    await print_welcome_log()
    yield  # === run app ===
    log.info("Shutting down")

    for t in background_tasks:
        t.stop()
    for t in background_tasks:
        await t.wait()
    await docker_stop_all_apps()
    await docker_shutdown_all_apps(force=True)
    await database.shutdown_database()


def _make_background_tasks() -> List[BackgroundTask]:
    s = settings()
    return [
        app_installation.worker.installation_worker,
        PeriodicTask(app_lifecycle.control_apps, s.apps.lifecycle.refresh_interval),
        PeriodicTask(peer.update_all_peer_pubkeys, 60),
        CronTask(
            app_usage_reporting.track_currently_installed_apps,
            s.apps.usage_reporting.tracking_schedule,
        ),
        CronTask(
            app_usage_reporting.report_app_usage,
            s.apps.usage_reporting.reporting_schedule,
        ),
        CronTask(
            scheduled_docker_prune_images,
            s.apps.pruning.schedule,
        ),
        CronTask(
            start_backup,
            cron=s.services.backup.timing.base_schedule,
            max_random_delay=s.services.backup.timing.max_random_delay,
        ),
        PeriodicTask(disk.update_disk_space, 30),
        websocket.ws_worker,
        PeriodicTask(telemetry.send_telemetry, s.telemetry.send_interval_seconds),
    ]


def _copy_traefik_static_config():
    s = settings()
    _disable_ssl = s.traefik.disable_ssl
    traefik_yml = "traefik_no_ssl.yml" if _disable_ssl else "traefik.yml"
    if _disable_ssl:
        log.warning("SSL disabled")

    source = Path.cwd() / "data" / traefik_yml
    with open(source, "r") as f:
        template = jinja2.Template(f.read())

    result = template.render({"acme_email": s.traefik.acme_email})

    root = Path(s.path_root)
    target = root / "core" / "traefik.yml"
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "w") as f:
        f.write(result)


async def print_welcome_log():
    params = {}
    i = await identity.get_default_identity()
    protocol = "http" if settings().traefik.disable_ssl else "https"
    shard_url = f"{protocol}://{i.domain}"
    params["shard_id"] = i.short_id
    params["shard_url_centered"] = _center(shard_url)

    async with db_conn() as conn:
        terminal_count = await db_terminals.count(conn)
    is_first_start = terminal_count == 0
    params["is_first_start"] = is_first_start
    if is_first_start:
        pairing_code = await make_pairing_code(deadline=10 * 60)
        pairing_link = f"{shard_url}/#/pair?code={pairing_code.code}"
        params["pairing_link_centered"] = _center(pairing_link)

    with open(Path.cwd() / "data" / "freeshard_ascii.jinja", "r") as f:
        welcome_log_template = jinja2.Template(f.read())

    welcome_log = welcome_log_template.render(params)
    print(welcome_log)


def _center(text: str) -> str:
    center_point = 27
    offset = center_point - len(text) // 2
    return " " * offset + text
