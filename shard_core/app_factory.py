import logging
import os
import sys
from contextlib import asynccontextmanager
from importlib.metadata import metadata
from pathlib import Path
from typing import List

import gconf
import jinja2
from fastapi import FastAPI
from pydantic import ValidationError
from requests import ConnectionError, HTTPError

from .db import init_database, migrate
from .db import identities, terminals, peers, installed_apps, tours, app_usage_track, key_value, util as db_util
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
from .service.app_installation.util import write_traefik_dyn_config
from .service.app_tools import (
    docker_stop_all_apps,
    docker_shutdown_all_apps,
    docker_prune_images,
)

from .service.backup import start_backup
from .service.pairing import make_pairing_code
from .util.async_util import PeriodicTask, BackgroundTask, CronTask
from .util.misc import str_to_bool
from .web import internal, public, protected, management

log = logging.getLogger(__name__)


def create_app():
    gconf.set_env_prefix("FREESHARD")
    # Only load config if not already loaded (e.g., by test fixtures)
    try:
        gconf.get("path_root")
        log.debug("Config already loaded, skipping config file load")
    except KeyError:
        if "CONFIG" in os.environ:
            for c in os.environ["CONFIG"].split(","):
                gconf.load(c)
        else:
            gconf.load("config.yml")
    configure_logging()

    init_database()
    migrate()  # Run database migrations at startup
    identity.init_default_identity()
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
    for module, level in gconf.get("log.levels").items():  # type: str, str
        logger = logging.getLogger() if module == "root" else logging.getLogger(module)
        logger.setLevel(getattr(logging, level.upper()))
        log.info(f"set logger for {module} to {level.upper()}")


@asynccontextmanager
async def lifespan(_):
    await write_traefik_dyn_config()
    await app_installation.login_docker_registries()
    await migration.migrate()
    await app_installation.refresh_init_apps()
    backup.ensure_backup_passphrase()
    try:
        await portal_controller.refresh_profile()
    except (ConnectionError, HTTPError, ValidationError) as e:
        log.error(f"could not refresh profile: {e}")

    background_tasks = _make_background_tasks()
    for t in background_tasks:
        t.start()

    log.info("Startup complete")
    print_welcome_log()
    yield  # === run app ===
    log.info("Shutting down")

    for t in background_tasks:
        t.stop()
    for t in background_tasks:
        await t.wait()
    await docker_stop_all_apps()
    await docker_shutdown_all_apps(force=True)


def _make_background_tasks() -> List[BackgroundTask]:
    return [
        app_installation.worker.installation_worker,
        PeriodicTask(
            app_lifecycle.control_apps, gconf.get("apps.lifecycle.refresh_interval")
        ),
        PeriodicTask(peer.update_all_peer_pubkeys, 60),
        CronTask(
            app_usage_reporting.track_currently_installed_apps,
            gconf.get("apps.usage_reporting.tracking_schedule"),
        ),
        CronTask(
            app_usage_reporting.report_app_usage,
            gconf.get("apps.usage_reporting.reporting_schedule"),
        ),
        CronTask(
            docker_prune_images,
            gconf.get("apps.pruning.schedule"),
        ),
        CronTask(
            start_backup,
            cron=gconf.get("services.backup.timing.base_schedule"),
            max_random_delay=gconf.get("services.backup.timing.max_random_delay"),
        ),
        PeriodicTask(disk.update_disk_space, 3),
        websocket.ws_worker,
        PeriodicTask(
            telemetry.send_telemetry, gconf.get("telemetry.send_interval_seconds")
        ),
    ]


def _copy_traefik_static_config():
    _disable_ssl = str_to_bool(gconf.get("traefik.disable_ssl", default="false"))
    traefik_yml = "traefik_no_ssl.yml" if _disable_ssl else "traefik.yml"
    if _disable_ssl:
        log.warning("SSL disabled")

    source = Path.cwd() / "data" / traefik_yml
    with open(source, "r") as f:
        template = jinja2.Template(f.read())

    result = template.render({"acme_email": gconf.get("traefik.acme_email")})

    root = Path(gconf.get("path_root"))
    target = root / "core" / "traefik.yml"
    target.parent.mkdir(parents=True, exist_ok=True)  # Create directory if not exists
    with open(target, "w") as f:
        f.write(result)


def print_welcome_log():
    params = {}
    i = identity.get_default_identity()
    protocol = (
        "http"
        if str_to_bool(gconf.get("traefik.disable_ssl", default="false"))
        else "https"
    )
    shard_url = f"{protocol}://{i.domain}"
    params["shard_id"] = i.short_id
    params["shard_url_centered"] = _center(shard_url)

    is_first_start = terminals.count() == 0
    params["is_first_start"] = is_first_start
    if is_first_start:
        pairing_code = make_pairing_code(deadline=10 * 60)
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
