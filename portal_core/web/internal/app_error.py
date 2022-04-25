import logging

from fastapi import APIRouter

log = logging.getLogger(__name__)

router = APIRouter()


@router.get('/app_error/{status}')
def app_error(status):
	return f'Splash for error {status}'
