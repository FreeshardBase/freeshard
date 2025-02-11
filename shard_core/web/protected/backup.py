import logging

from fastapi import Header, HTTPException, APIRouter, status
from tinydb import Query

from shard_core.database import database
from shard_core.database.database import terminals_table
from shard_core.model.backup import BackupPassphraseResponse, BackupInfoResponse, BackupPassphraseLastAccessInfoDB, \
	BackupPassphraseLastAccessInfoResponse
from shard_core.model.terminal import Terminal
from shard_core.service import backup

log = logging.getLogger(__name__)

router = APIRouter(
	prefix='/backup',
)


@router.get('/info', response_model=BackupInfoResponse)
async def get_backup_info():
	try:
		last_access_info_db = BackupPassphraseLastAccessInfoDB.parse_obj(
			database.get_value(backup.STORE_KEY_BACKUP_PASSPHRASE_LAST_ACCESS)
		)
	except KeyError:
		last_access_info_response = None
	else:
		with terminals_table() as terminals:
			terminal_db = terminals.get(Query().id == last_access_info_db.terminal_id)
		terminal_name = Terminal.parse_obj(terminal_db).name if terminal_db else 'Unknown'
		last_access_info_response = BackupPassphraseLastAccessInfoResponse(
			**last_access_info_db.dict(),
			terminal_name=terminal_name
		)

	return BackupInfoResponse(
		last_report=backup.get_latest_backup_report(),
		last_passphrase_access_info=last_access_info_response
	)


@router.get('/passphrase', response_model=BackupPassphraseResponse)
async def get_backup_passphrase(x_ptl_client_id: str = Header(None)):
	if not x_ptl_client_id:
		raise HTTPException(status_code=400, detail='Missing X-Ptl-Client-Id header')
	passphrase = backup.get_backup_passphrase(x_ptl_client_id)
	return BackupPassphraseResponse(passphrase=passphrase)


@router.post('/start', status_code=status.HTTP_204_NO_CONTENT)
async def start_backup():
	# todo: make periodic backup
	try:
		await backup.start_backup()
	except backup.BackupStartFailedError as e:
		raise HTTPException(status_code=500, detail=str(e))
