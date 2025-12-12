# DO NOT MODIFY - copied from freeshard-controller

from typing import List

from pydantic import BaseModel


class SendEmailRequest(BaseModel):
    to: str
    subject: str
    body: List[str]
