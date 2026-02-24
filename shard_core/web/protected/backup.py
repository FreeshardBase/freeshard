import logging

from fastapi import Header, HTTPException, APIRouter, status

from shard_core.database import database
from shard_core.database.connection import db_conn
from shard_core.database import terminals as terminals_db
from shard_core.data_model.backup import (
    BackupPassphraseResponse,
    BackupInfoResponse,
    BackupPassphraseLastAccessInfoDB,
    BackupPassphraseLastAccessInfoResponse,
)
from shard_core.data_model.terminal import Terminal
from shard_core.service import backup

log = logging.getLogger(__name__)

router = APIRouter(
    prefix="/backup",
)


@router.get("/info", response_model=BackupInfoResponse)
async def get_backup_info():
    try:
        last_access_info_db = BackupPassphraseLastAccessInfoDB.parse_obj(
            await database.get_value(backup.STORE_KEY_BACKUP_PASSPHRASE_LAST_ACCESS)
        )
    except KeyError:
        last_access_info_response = None
    else:
        async with db_conn() as conn:
            terminal_db = await terminals_db.get_by_id(conn, last_access_info_db.terminal_id)
        terminal_name = (
            Terminal.parse_obj(terminal_db).name if terminal_db else "Unknown"
        )
        last_access_info_response = BackupPassphraseLastAccessInfoResponse(
            **last_access_info_db.dict(), terminal_name=terminal_name
        )

    return BackupInfoResponse(
        last_report=await backup.get_latest_backup_report(),
        last_passphrase_access_info=last_access_info_response,
    )


@router.get("/passphrase", response_model=BackupPassphraseResponse)
async def get_backup_passphrase(x_ptl_client_id: str = Header(None)):
    if not x_ptl_client_id:
        raise HTTPException(status_code=400, detail="Missing X-Ptl-Client-Id header")
    passphrase = await backup.get_backup_passphrase(x_ptl_client_id)
    return BackupPassphraseResponse(passphrase=passphrase)


@router.post("/start", status_code=status.HTTP_204_NO_CONTENT)
async def start_backup():
    # todo: make periodic backup
    try:
        await backup.start_backup()
    except backup.BackupStartFailedError as e:
        raise HTTPException(status_code=500, detail=str(e))
