# DO NOT MODIFY - copied from freeshard-controller

from typing import Dict, Tuple

from pydantic import BaseModel


class MonthlyBreakdown(BaseModel):
    amount: int
    nr_of_shards: int


class RevenueShare(BaseModel):
    total_amount: int
    monthly_breakdown: Dict[Tuple[int, int], MonthlyBreakdown]


class RevenueShares(BaseModel):
    shares: Dict[str, RevenueShare] = {}
