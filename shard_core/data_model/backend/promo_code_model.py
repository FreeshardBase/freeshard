# DO NOT MODIFY - copied from freeshard-controller

from datetime import datetime
from typing import List

from pydantic import BaseModel


class PromoCodeDb(BaseModel):
    id: int
    code: str
    created: datetime
    max_uses: int
    lifetime_h: int | None = None
    is_active: bool


class PromoCodeUse(BaseModel):
    id: int
    promo_code_id: int
    shard_id: int | None
    used: datetime


class PromoCodeResult(PromoCodeDb):
    uses: List[PromoCodeUse] = []
