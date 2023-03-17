import logging

import gconf
from fastapi import APIRouter, status, Response
from pydantic import BaseModel

from portal_core.service.signed_call import signed_request

log = logging.getLogger(__name__)

router = APIRouter(
	prefix='/feedback',
)


class QuickFeedbackInput(BaseModel):
	text: str


@router.post('/quick', status_code=status.HTTP_201_CREATED)
def post_quick_feedback(feedback: QuickFeedbackInput):
	log.debug(f'Posting quick feedback: {feedback.text}')
	api_url = gconf.get('management.api_url')
	url = f'{api_url}/quick_feedback'
	response = signed_request('POST', url, json=feedback.dict())
	return Response(status_code=response.status_code, content=response.content)
