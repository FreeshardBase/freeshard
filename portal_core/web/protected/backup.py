import asyncio
import logging
from datetime import datetime
from pathlib import Path
from requests.exceptions import HTTPError
import gconf
from fastapi import APIRouter
from fastapi import HTTPException
from starlette.responses import StreamingResponse
from zipstream import ZipStream

from portal_core.service.backup import sync_directories
from portal_core.service.identity import get_default_identity
from portal_core.service.portal_controller import get_backup_sas_url
from portal_core.util import signals

log = logging.getLogger(__name__)

router = APIRouter(
	prefix='/backup',
)


@router.post('/sync')
async def sync_backup():
	try:
		sas_url_response = await get_backup_sas_url()
	except HTTPError as e:
		upstream_error = e.response.json()['detail']
		raise HTTPException(status_code=e.response.status_code, detail=f'Failed to get SAS token: {upstream_error}')
	try:
		directories = [Path.cwd() / 'run']
		log.debug(f'syncing directories: {directories} using sas url {sas_url_response.sas_url}')
		# todo: add password
		task = asyncio.create_task(
			sync_directories(directories, sas_url_response.container_name, sas_url_response.sas_url, 'foobar'))

		def on_task_done(task):
			if task.exception():
				log.error(f'Backup failed: {task.exception()}')
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
