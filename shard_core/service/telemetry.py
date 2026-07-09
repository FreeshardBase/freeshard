import datetime
import logging
import re
from pathlib import Path
from typing import List, Optional, Tuple

from shard_core.data_model.backend.telemetry_model import Telemetry, PauseTierTelemetry
from shard_core.service import pause_metrics
from shard_core.service.freeshard_controller import call_freeshard_controller
from shard_core.settings import settings
from shard_core.util.signals import on_terminal_auth, on_request_to_app

log = logging.getLogger(__name__)


no_of_requests: int = 0
last_send: datetime.datetime = datetime.datetime.now(datetime.timezone.utc)

MEMINFO_PATH = Path("/proc/meminfo")


@on_terminal_auth.connect
@on_request_to_app.connect
async def record_request(_):
    if not settings().telemetry.enabled:
        return

    global no_of_requests
    no_of_requests += 1


def _percentile(samples: List[float], fraction: float) -> float:
    if not 0.0 <= fraction <= 1.0:
        raise ValueError(f"fraction must be between 0 and 1, was {fraction}")
    ordered = sorted(samples)
    return ordered[round(fraction * (len(ordered) - 1))]


def _read_swap_kib() -> Tuple[Optional[int], Optional[int]]:
    try:
        text = MEMINFO_PATH.read_text()
    except OSError:
        return None, None
    total = re.search(r"^SwapTotal:\s+(\d+) kB", text, re.MULTILINE)
    free = re.search(r"^SwapFree:\s+(\d+) kB", text, re.MULTILINE)
    return (
        int(total.group(1)) if total else None,
        int(free.group(1)) if free else None,
    )


def _build_pause_tier() -> Optional[PauseTierTelemetry]:
    m = pause_metrics
    if not (
        m.app_transitions
        or m.pause_latencies_ms
        or m.unpause_latencies_ms
        or m.psi_snapshots
    ):
        return None
    swap_total_kib, swap_free_kib = _read_swap_kib()
    return PauseTierTelemetry(
        transitions={
            app: dict(counters) for app, counters in m.app_transitions.items()
        },
        pause_latency_ms_p50=(
            _percentile(m.pause_latencies_ms, 0.5) if m.pause_latencies_ms else None
        ),
        pause_latency_ms_p95=(
            _percentile(m.pause_latencies_ms, 0.95) if m.pause_latencies_ms else None
        ),
        unpause_latency_ms_p50=(
            _percentile(m.unpause_latencies_ms, 0.5) if m.unpause_latencies_ms else None
        ),
        unpause_latency_ms_p95=(
            _percentile(m.unpause_latencies_ms, 0.95)
            if m.unpause_latencies_ms
            else None
        ),
        psi_some_avg10_snapshots=list(m.psi_snapshots),
        swap_total_kib=swap_total_kib,
        swap_free_kib=swap_free_kib,
    )


async def send_telemetry():
    if not settings().telemetry.enabled:
        return

    global last_send
    global no_of_requests
    now = datetime.datetime.now(datetime.timezone.utc)

    telemetry = Telemetry(
        start_time=last_send,
        end_time=now,
        no_of_requests=no_of_requests,
        pause_tier=_build_pause_tier(),
    )
    try:
        await call_freeshard_controller(
            "api/telemetry",
            method="POST",
            body=telemetry.model_dump_json().encode(),
        )
    except Exception as e:
        log.error(f"Error during telemetry sending: {e}")
        return

    duration = now - last_send
    log.debug(
        f"Sent telemetry: {no_of_requests} requests during the last {duration.total_seconds():.0} seconds"
    )

    last_send = now
    no_of_requests = 0
    pause_metrics.reset()
