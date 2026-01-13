# DO NOT MODIFY - copied from freeshard-controller

import datetime

from pydantic import BaseModel


class Telemetry(BaseModel):
    start_time: datetime.datetime
    end_time: datetime.datetime
    no_of_requests: int
