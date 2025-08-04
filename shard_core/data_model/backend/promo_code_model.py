# DO NOT MODIFY - copied from freeshard-controller

from datetime import datetime
from typing import List

from pydantic import BaseModel


class PromoCodeDb(BaseModel):
    id: int
    code: str
    created: datetime
    max_uses: int
    is_active: bool


class PromoCodeUse(BaseModel):
    id: int
    used: datetime


class PromoCodeResult(PromoCodeDb):
    uses: List[PromoCodeUse]


class PromoCodeCheckResponse(BaseModel):
    code: str
    max_uses: int
    uses_left: int
