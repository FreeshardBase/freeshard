import logging

from fastapi import APIRouter, status

from shard_core.service.pairing import PairingCode, make_pairing_code

log = logging.getLogger(__name__)

router = APIRouter(
    prefix="/pairing_code",
)


@router.get("", response_model=PairingCode, status_code=status.HTTP_201_CREATED)
def new_pairing_code(deadline: int = None):
    pairing_code = make_pairing_code(deadline=deadline)
    log.info("created new terminal pairing code by freeshard-controller")
    return pairing_code
