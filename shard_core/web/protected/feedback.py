import logging

import gconf
from fastapi import APIRouter, status
from pydantic import BaseModel

from shard_core.service.signed_call import signed_request

log = logging.getLogger(__name__)

router = APIRouter(
    prefix="/feedback",
)


class QuickFeedbackInput(BaseModel):
    text: str


@router.post("/quick", status_code=status.HTTP_201_CREATED)
async def post_quick_feedback(feedback: QuickFeedbackInput):
    log.debug(f"Posting quick feedback: {feedback.text}")
    controller_url = gconf.get("freeshard_controller.base_url")
    return await signed_request(
        "POST", f"{controller_url}/api/feedback", json=feedback.dict()
    )
