import logging

from fastapi import APIRouter, status
from pydantic import BaseModel

from shard_core.service.signed_call import signed_request
from shard_core.settings import settings

log = logging.getLogger(__name__)

router = APIRouter(
    prefix="/feedback",
)


class QuickFeedbackInput(BaseModel):
    text: str


@router.post("/quick", status_code=status.HTTP_201_CREATED)
async def post_quick_feedback(feedback: QuickFeedbackInput):
    log.debug(f"Posting quick feedback: {feedback.text}")
    controller_url = settings().freeshard_controller.base_url
    response = await signed_request(
        "POST", f"{controller_url}/api/feedback", json=feedback.model_dump()
    )
    # Do not return the raw requests.Response: it is a live streamed object that
    # FastAPI cannot JSON-encode, which turned every real-shard submit into a 500
    # (issue #245). Surface a controller-side failure as an error and otherwise
    # let the route answer 201 with no body.
    response.raise_for_status()
