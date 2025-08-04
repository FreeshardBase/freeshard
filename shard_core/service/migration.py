import logging

from shard_core.database.database import get_db
from shard_core.service.app_installation import install_app_from_store, AppDoesNotExist

log = logging.getLogger(__name__)


async def migrate():
    with get_db() as db:
        if "apps" not in db.tables():
            log.debug("no migration needed")
            return

        if "apps" in db.tables() and "installed_apps" in db.tables():
            log.warning(
                "incomplete migration detected, dropping apps table and skipping migration"
            )
            db.drop_table("apps")
            return

        previously_installed_apps = db.table("apps").all()

    log.info(f'found apps to migrate: {[a["name"] for a in previously_installed_apps]}')

    for app in previously_installed_apps:
        try:
            await install_app_from_store(app["name"], app["installation_reason"])
        except AppDoesNotExist:
            log.warning(f'app {app["name"]} does not exist in store, skipping')

    with get_db() as db:
        db.drop_table("apps")
