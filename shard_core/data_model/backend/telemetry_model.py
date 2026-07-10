# DO NOT MODIFY - copied from freeshard-controller

import datetime
from typing import Dict, List, Optional

from pydantic import BaseModel


class PauseTierTelemetry(BaseModel):
    """Metrics from the shard_core PAUSED+PAGED app tier (FreeshardBase/freeshard#81).

    Sent by shards with the pause tier enabled; absent (None) from older shards
    and from shards with the feature flag off.
    """

    # per-app transition counts, e.g. {"immich": {"running_to_paused": 3, "paused_to_running": 2}}
    transitions: Dict[str, Dict[str, int]] = {}
    pause_latency_ms_p50: Optional[float] = None
    pause_latency_ms_p95: Optional[float] = None
    unpause_latency_ms_p50: Optional[float] = None
    unpause_latency_ms_p95: Optional[float] = None
    # PSI `some avg10` sampled at each control cycle within the reporting interval
    psi_some_avg10_snapshots: List[float] = []
    swap_total_kib: Optional[int] = None
    swap_free_kib: Optional[int] = None


class Telemetry(BaseModel):
    start_time: datetime.datetime
    end_time: datetime.datetime
    no_of_requests: int
    pause_tier: Optional[PauseTierTelemetry] = None
