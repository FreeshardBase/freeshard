import logging

from fastapi import APIRouter, status
from pydantic import BaseModel

from shard_core.service.websocket import ws_worker

log = logging.getLogger(__name__)

router = APIRouter(
    prefix="/notify",
)


class NotifyRequest(BaseModel):
    type: str


@router.post("", status_code=status.HTTP_204_NO_CONTENT)
async def notify(body: NotifyRequest):
    try:
        ws_worker.broadcast_message(body.type)
    except Exception:
        log.exception("failed to broadcast notify message of type %s", body.type)
