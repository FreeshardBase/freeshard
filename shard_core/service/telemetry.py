import datetime
import logging

from shard_core.data_model.backend.telemetry_model import Telemetry
from shard_core.service.freeshard_controller import call_freeshard_controller
from shard_core.util.signals import on_terminal_auth, on_request_to_app

log = logging.getLogger(__name__)


no_of_requests: int = 0
last_send: datetime.datetime = datetime.datetime.now(datetime.timezone.utc)


@on_terminal_auth.connect
@on_request_to_app.connect
def record_request(_):
    global no_of_requests
    no_of_requests += 1


async def send_telemetry():
    global last_send
    global no_of_requests
    now = datetime.datetime.now(datetime.timezone.utc)

    telemetry = Telemetry(
        start_time=last_send, end_time=now, no_of_requests=no_of_requests
    )
    try:
        await call_freeshard_controller(
            "api/telemetry",
            method="POST",
            body=telemetry.json().encode(),
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
