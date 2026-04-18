import asyncio
import datetime
import json
import logging
import subprocess
import traceback
from pathlib import Path
from typing import List
from urllib.parse import urlparse, urlunparse

from azure.storage.blob import BlobClient
from requests import HTTPError

from shard_core.database import database
from shard_core.database.connection import db_conn
from shard_core.database import backups as db_backups
from shard_core.data_model.backup import (
    BackupReport,
    BackupStats,
    BackupPassphraseLastAccessInfoDB,
)
from shard_core.settings import settings
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
--create-empty-src-dirs --stats-log-level NOTICE --stats 1000m --use-json-log
"""

CLEARTEXT_COMMAND_TEMPLATE = """
rclone
--azureblob-sas-url {sas_token}
sync {directory} :azureblob:{container_name}/{directory}
--create-empty-src-dirs --stats-log-level NOTICE --stats 1000m --use-json-log
"""


async def start_backup():
    s = settings()
    path_root = Path(s.path_root)
    directories = [path_root / d for d in s.services.backup.directories]

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
                    rclone_stats=rclone_stats,
                )
            )

        overall_end_time = datetime.datetime.now(datetime.timezone.utc)
        report = BackupReport(
            directories=dir_stats,
            startTime=overall_start_time,
            endTime=overall_end_time,
        )
        async with db_conn() as conn:
            await db_backups.insert(conn, report.model_dump())
        _write_marker_blob(container_name, sas_token)
        log.info("Backup done")


def _write_marker_blob(container_name: str, sas_token: str):
    """Write a marker blob to the backup container to record the time of the last backup.

    The blob's Last-Modified timestamp on Azure is updated on every call, giving the
    controller a reliable recency signal regardless of whether any data blobs changed.
    """
    try:
        # sas_token is a container-level SAS URL of the form:
        #   https://account.blob.core.windows.net/container?sv=...&sig=...
        # BlobClient.from_blob_url expects the blob path inserted before the query:
        #   https://account.blob.core.windows.net/container/_last_backup?sv=...&sig=...
        parsed = urlparse(sas_token)
        blob_url = urlunparse(parsed._replace(path=f"/{container_name}/_last_backup"))
        blob_client = BlobClient.from_blob_url(blob_url)
        timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
        blob_client.upload_blob(timestamp, overwrite=True)
        log.debug("Wrote _last_backup marker blob")
    except Exception:
        log.warning("Failed to write _last_backup marker blob", exc_info=True)


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
    path_root = Path(settings().path_root)
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
    path_root = Path(settings().path_root)
    return directory.relative_to(path_root)


async def get_latest_backup_report() -> BackupReport | None:
    async with db_conn() as conn:
        row = await db_backups.get_latest(conn)
    return BackupReport.model_validate(row) if row else None


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
    await database.set_value(
        STORE_KEY_BACKUP_PASSPHRASE_LAST_ACCESS, last_access_info.model_dump()
    )
    return passphrase


class BackupInProgressError(Exception):
    pass


class BackupStartFailedError(Exception):
    pass
