# DO NOT MODIFY - copied from freeshard-controller

import datetime

from pydantic import BaseModel


class EmailVerificationLogDb(BaseModel):
    id: int
    shard_id: int
    sent_at: datetime.datetime
    recipient: str
