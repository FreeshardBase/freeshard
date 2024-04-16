import asyncio
import logging
import traceback
from datetime import datetime
from pathlib import Path

import gconf
from fastapi import Header, Request, HTTPException, APIRouter
from requests.exceptions import HTTPError
from starlette.responses import StreamingResponse
from zipstream import ZipStream

from portal_core.database import database
from portal_core.model.backup import BackupPassphraseResponse, BackupInfoResponse
from portal_core.service import backup
from portal_core.service.backup import sync_directories
from portal_core.service.identity import get_default_identity
from portal_core.service.portal_controller import get_backup_sas_url
from portal_core.util import signals

log = logging.getLogger(__name__)

router = APIRouter(
	prefix='/backup',
)


@router.get('/info', response_model=BackupInfoResponse)
async def get_backup_info():
	try:
		last_access_info = database.get_value(backup.STORE_KEY_BACKUP_PASSPHRASE_LAST_ACCESS)
	except KeyError:
		last_access_info = None

	return BackupInfoResponse(
		last_report=backup.get_latest_backup_report(),
		last_passphrase_access_info=last_access_info
	)


@router.get('/passphrase', response_model=BackupPassphraseResponse)
async def get_backup_passphrase(request: Request, x_ptl_client_id: str = Header(None)):
	if not x_ptl_client_id:
		raise HTTPException(status_code=400, detail='Missing X-Ptl-Client-Id header')
	client_ip = request.client.host
	passphrase = backup.get_backup_passphrase(x_ptl_client_id, client_ip)
	return BackupPassphraseResponse(passphrase=passphrase)


@router.post('/sync')
async def sync_backup():
	path_root = Path(gconf.get('path_root'))
	directories = [path_root / d for d in gconf.get('services.backup.directories')]

	try:
		sas_url_response = await get_backup_sas_url()
	except HTTPError as e:
		raise HTTPException(status_code=e.response.status_code, detail=f'Failed to get SAS token: {e}')
	try:
		task = asyncio.create_task(
			sync_directories(directories, sas_url_response.container_name, sas_url_response.sas_url))

		def on_task_done(task: asyncio.Task):
			if task.exception():
				log.error('Backup failed\n' + ''.join(traceback.format_exception(task.exception())))
				signals.on_backup_done.send(task.exception())
			else:
				signals.on_backup_done.send()

		task.add_done_callback(on_task_done)

		return {"message": "Sync started."}
	except Exception as e:
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
