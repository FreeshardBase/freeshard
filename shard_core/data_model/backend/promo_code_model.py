# DO NOT MODIFY - copied from freeshard-controller

from datetime import datetime
from typing import Annotated, List

from pydantic import BaseModel, Field


class PromoCodeDb(BaseModel):
    id: int
    code: str
    created: datetime
    max_uses: int
    lifetime_h: Annotated[int, Field(ge=1)] | None = None
    is_active: bool
    display_text: str | None = None


class PromoCodeUse(BaseModel):
    id: int
    promo_code_id: int
    shard_id: int | None
    used: datetime


class PromoCodeResult(PromoCodeDb):
    uses: List[PromoCodeUse] = []


class PromoCodeValidation(BaseModel):
    id: int
    max_uses: int
    is_active: bool
    uses_count: int
    display_text: str | None = None


class PromoCodeValidationResult(BaseModel):
    display_text: str | None = None


class PromoCodeUpdate(BaseModel):
    display_text: str | None = None
    max_uses: int | None = None
    lifetime_h: Annotated[int | None, Field(ge=1)] = None
