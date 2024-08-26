import logging

from fastapi import APIRouter, status

from portal_core.service import disk

log = logging.getLogger(__name__)

router = APIRouter(
	prefix='/stats',
)


@router.get('/disk', status_code=status.HTTP_200_OK, response_model=disk.DiskUsage)
async def disk_usage():
	return disk.current_disk_usage
