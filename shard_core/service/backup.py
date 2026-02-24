import asyncio
import datetime
import json
import logging
import subprocess
import traceback
from pathlib import Path
from typing import List

import gconf
from requests import HTTPError

from shard_core.database import database
from shard_core.database.connection import db_conn
from shard_core.database import backups as backups_db
from shard_core.data_model.backup import (
    BackupReport,
    BackupStats,
    BackupPassphraseLastAccessInfoDB,
)
from shard_core.service.portal_controller import get_backup_sas_url
from shard_core.util import passphrase as passphrase_util, signals

log = logging.getLogger(__name__)

STORE_KEY_BACKUP_PASSPHRASE = "backup_passphrase"
STORE_KEY_BACKUP_PASSPHRASE_LAST_ACCESS = "backup_passphrase_last_access"
BACKUP_IN_PROGESS_LOCK = asyncio.Lock()

COMMAND_TEMPLATE = """
rclone
--azureblob-sas-url {sas_token}
--crypt-password {obscured_password}
--crypt-remote :azureblob:{container_name}
sync {directory} :crypt:{container_name}/{directory}
--stats-log-level NOTICE --stats 1000m --use-json-log
"""

CLEARTEXT_COMMAND_TEMPLATE = """
rclone
--azureblob-sas-url {sas_token}
sync {directory} :azureblob:{container_name}/{directory}
--stats-log-level NOTICE --stats 1000m --use-json-log
"""


async def start_backup():
    path_root = Path(gconf.get("path_root"))
    directories = [path_root / d for d in gconf.get("services.backup.directories")]

    if is_backup_in_progress():
        raise BackupStartFailedError("Sync in progress, please try again later.")

    try:
        sas_url_response = await get_backup_sas_url()
    except HTTPError as e:
        raise BackupStartFailedError(f"Failed to get SAS token: {e}")

    task = asyncio.create_task(
        backup_directories(
            directories, sas_url_response.container_name, sas_url_response.sas_url
        )
    )

    async def on_task_done(task: asyncio.Task):
        if task.exception():
            log.error(
                "Backup failed\n"
                + "".join(traceback.format_exception(task.exception()))
            )
            signals.on_backup_update.send(task.exception())
        else:
            signals.on_backup_update.send()

    task.add_done_callback(lambda task: asyncio.create_task(on_task_done(task)))


async def backup_directories(
    directories: List[Path], container_name: str, sas_token: str
):
    if BACKUP_IN_PROGESS_LOCK.locked():
        raise BackupInProgressError()

    async with BACKUP_IN_PROGESS_LOCK:
        overall_start_time = datetime.datetime.now(datetime.timezone.utc)
        obscured_passphrase = await _get_obscured_passphrase()
        dir_stats = []

        log.info(
            f"Backing up directories {[str(d) for d in directories]} to container {container_name}"
        )
        for directory in directories:
            if not directory.is_dir():
                log.error(
                    f"Directory {directory} cannot be backed up because it does not exist"
                )
                continue

            start_time = datetime.datetime.now(datetime.timezone.utc)
            rel_directory = _get_relative_directory(directory)
            rclone_stats = await _backup_directory(
                container_name,
                rel_directory,
                obscured_passphrase,
                sas_token,
            )
            end_time = datetime.datetime.now(datetime.timezone.utc)

            dir_stats.append(
                BackupStats(
                    directory=str(rel_directory),
                    startTime=start_time,
                    endTime=end_time,
                    **rclone_stats,
                )
            )

        overall_end_time = datetime.datetime.now(datetime.timezone.utc)
        report = BackupReport(
            directories=dir_stats,
            startTime=overall_start_time,
            endTime=overall_end_time,
        )
        async with db_conn() as conn:
            await backups_db.insert(conn, report.dict())
        log.info("Backup done")


def is_backup_in_progress():
    return BACKUP_IN_PROGESS_LOCK.locked()


async def _backup_directory(
    container_name, rel_directory, obscured_passphrase, sas_token
):
    command = COMMAND_TEMPLATE.format(
        sas_token=sas_token,
        obscured_password=obscured_passphrase,
        container_name=container_name,
        directory=rel_directory,
    )
    path_root = Path(gconf.get("path_root"))
    process = await asyncio.create_subprocess_exec(
        *command.split(),
        cwd=path_root,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    try:
        last_entry = stderr.decode().split("\n")[-2]  # last line ends with newline
        rclone_result = json.loads(last_entry)
    except json.JSONDecodeError:
        log.error(f"Failed to parse rclone output: {stderr.decode()}")
        raise
    return rclone_result["stats"]


async def _get_obscured_passphrase():
    passphrase = await database.get_value(STORE_KEY_BACKUP_PASSPHRASE)
    obscured_passphrase = subprocess.run(
        ["rclone", "obscure", passphrase], capture_output=True, text=True
    ).stdout.strip()
    return obscured_passphrase


def _get_relative_directory(directory: Path) -> Path:
    path_root = Path(gconf.get("path_root"))
    return directory.relative_to(path_root)


async def get_latest_backup_report() -> BackupReport | None:
    async with db_conn() as conn:
        latest_stats = await backups_db.get_latest(conn)
    return BackupReport.parse_obj(latest_stats) if latest_stats else None


async def ensure_backup_passphrase():
    try:
        await database.get_value(STORE_KEY_BACKUP_PASSPHRASE)
    except KeyError:
        passphrase_numbers = passphrase_util.generate_passphrase_numbers(10)
        passphrase = passphrase_util.get_passphrase(passphrase_numbers)
        await database.set_value(STORE_KEY_BACKUP_PASSPHRASE, passphrase)
        log.info("Generated new backup passphrase")
    else:
        log.info("Backup passphrase already exists")


async def get_backup_passphrase(terminal_id: str) -> str:
    passphrase = await database.get_value(STORE_KEY_BACKUP_PASSPHRASE)
    last_access_info = BackupPassphraseLastAccessInfoDB(
        time=datetime.datetime.now(datetime.timezone.utc),
        terminal_id=terminal_id,
    )
    await database.set_value(STORE_KEY_BACKUP_PASSPHRASE_LAST_ACCESS, last_access_info.dict())
    return passphrase


class BackupInProgressError(Exception):
    pass


class BackupStartFailedError(Exception):
    pass
