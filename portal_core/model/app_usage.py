import datetime
from typing import List

from pydantic import BaseModel


class AppUsageTrack(BaseModel):
	timestamp: datetime.datetime
	installed_apps: List[str]
