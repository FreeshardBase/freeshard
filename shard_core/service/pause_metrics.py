"""In-memory accumulators for PAUSED+PAGED tier metrics.

Kept separate from service.telemetry (which packages and sends them) so that
app_tools and app_lifecycle can record without importing telemetry's
controller-client dependency chain — importing telemetry from app_tools
trips the pre-existing signed_call/portal_controller import cycle.

Reset after each successful telemetry send. Lost on restart, like every
other telemetry counter.
"""

from typing import Dict, List

from shard_core.settings import settings

app_transitions: Dict[str, Dict[str, int]] = {}
pause_latencies_ms: List[float] = []
unpause_latencies_ms: List[float] = []
psi_snapshots: List[float] = []

_MAX_LATENCY_SAMPLES = 1000
_MAX_PSI_SNAPSHOTS = 120


def record_app_transition(app_name: str, from_status, to_status):
    if not settings().telemetry.enabled:
        return
    key = f"{from_status.value}_to_{to_status.value}"
    counters = app_transitions.setdefault(app_name, {})
    counters[key] = counters.get(key, 0) + 1


def record_pause_latency(milliseconds: float):
    if not settings().telemetry.enabled:
        return
    if len(pause_latencies_ms) < _MAX_LATENCY_SAMPLES:
        pause_latencies_ms.append(milliseconds)


def record_unpause_latency(milliseconds: float):
    if not settings().telemetry.enabled:
        return
    if len(unpause_latencies_ms) < _MAX_LATENCY_SAMPLES:
        unpause_latencies_ms.append(milliseconds)


def record_psi_snapshot(psi_some_avg10: float):
    if not settings().telemetry.enabled:
        return
    if len(psi_snapshots) < _MAX_PSI_SNAPSHOTS:
        psi_snapshots.append(psi_some_avg10)


def reset():
    app_transitions.clear()
    pause_latencies_ms.clear()
    unpause_latencies_ms.clear()
    psi_snapshots.clear()
