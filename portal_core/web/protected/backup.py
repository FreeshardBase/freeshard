import logging
from datetime import datetime
from pathlib import Path

import gconf
from fastapi import Header, HTTPException, APIRouter, status
from starlette.responses import StreamingResponse
from tinydb import Query
from zipstream import ZipStream

from portal_core.old_database import database
from portal_core.model.backup import BackupPassphraseResponse, BackupInfoResponse, BackupPassphraseLastAccessInfoDB, \
	BackupPassphraseLastAccessInfoResponse
from portal_core.service import backup
from portal_core.service.identity import get_default_identity
from portal_core.service.terminal import get_terminal_by_id

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
		terminal_db = get_terminal_by_id(last_access_info_db.terminal_id)
		last_access_info_response = BackupPassphraseLastAccessInfoResponse(
			**last_access_info_db.model_dump(),
			terminal_name=terminal_db.name
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


@router.get('/export')
def export_backup():
	log.info('exporting full backup')
	zs = ZipStream(content_generator())
	return StreamingResponse(
		zs.stream(),
		media_type='application/zip',
		headers={'Content-Disposition': f'attachment; filename={get_filename()}'}
	)


def get_filename():
	default_identity_id = get_default_identity().short_id
	formatted_now = datetime.now().strftime("%Y-%m-%d %H-%M")
	filename = f'Backup of Portal {default_identity_id} - {formatted_now}.zip'
	return filename


def content_generator():
	yield from included_dirs()


def included_dirs():
	path_root = Path(gconf.get('path_root'))
	globs = gconf.get('services.backup.included_globs')
	for glob in globs:
		for path in path_root.glob(glob):
			if path.is_file():
				yield {
					'file': str(path),
					'name': str(path.relative_to(path_root)),
					'compression': 'deflate',
				}
