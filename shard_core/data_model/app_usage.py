import datetime
from typing import List, Dict

from pydantic import BaseModel


class AppUsageTrack(BaseModel):
    timestamp: datetime.datetime
    installed_apps: List[str]


class AppUsageReport(BaseModel):
    year: int
    month: int
    usage: Dict[str, float]
