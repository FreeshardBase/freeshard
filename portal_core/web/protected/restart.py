import logging
from datetime import datetime

from fastapi import APIRouter, status

log = logging.getLogger(__name__)

router = APIRouter(
	prefix='/restart',
)


@router.post('', status_code=status.HTTP_204_NO_CONTENT)
def restart():
	with open('/core/restart_core', 'w') as f:
		f.write(datetime.now().isoformat())
	log.info('scheduled restart of portal services')
