import logging
from datetime import datetime
from pathlib import Path

import docker
import gconf
from docker.models.containers import Container
from fastapi import APIRouter
from starlette.responses import StreamingResponse
from zipstream import ZipStream

from portal_core.service.identity import get_default_identity

log = logging.getLogger(__name__)

router = APIRouter(
	prefix='/backup',
)


@router.get('/export')
def export_backup():
	zs = ZipStream(content_generator())

	default_identity_id = get_default_identity().short_id
	formatted_now = datetime.now().strftime("%Y-%m-%d %H-%M")
	filename = f'Backup of Portal {default_identity_id} - {formatted_now}.zip'

	log.info('exporting full backup')
	return StreamingResponse(
		zs.stream(),
		media_type='application/zip',
		headers={'Content-Disposition': f'attachment; filename={filename}'}
	)


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


def postgres_dump():
	postgres_user = gconf.get('services.postgres.user')
	postgres_password = gconf.get('services.postgres.password')

	docker_client = docker.from_env()
	postgres_container: Container = docker_client.containers.get('postgres')
	pg_dumpall = postgres_container.exec_run(
		['pg_dumpall', '--username', postgres_user],
		environment={'PGPASSWORD': postgres_password},
		stdout=True, stream=True,
	)

	return {
		'stream': pg_dumpall.output,
		'name': 'postgres_dump.sql'
	}
