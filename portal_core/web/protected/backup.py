import logging
from datetime import datetime
from pathlib import Path

import gconf
from fastapi import APIRouter
from starlette.responses import StreamingResponse
from tinydb import Query
from zipstream import ZipStream

from portal_core.database.database import identities_table
from portal_core.model.identity import Identity

log = logging.getLogger(__name__)

router = APIRouter(
	prefix='/backup',
)


@router.get('/export')
def export_backup():
	with identities_table() as identities:
		default_identity = Identity(**identities.get(Query().is_default == True))

	path_root = Path(gconf.get('path_root'))
	included_dirs = gconf.get('services.backup.included_dirs')

	def files_generator():
		for included_dir in included_dirs:
			for path in (path_root / included_dir).rglob('*'):
				if path.is_file():
					yield {
						'file': str(path),
						'name': str(path.relative_to(path_root)),
						'compression': 'deflate',
					}

	zs = ZipStream(files_generator())

	filename = f'Backup of Portal {default_identity.short_id} - {datetime.now().strftime("%Y-%m-%d %H-%M")}.zip'
	log.info('exported full backup')
	return StreamingResponse(
		zs.stream(),
		media_type='application/zip',
		headers={'Content-Disposition': f'attachment; filename={filename}'}
	)
