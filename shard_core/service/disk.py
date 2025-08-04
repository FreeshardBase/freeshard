import logging
import shutil

from pydantic import BaseModel

from shard_core.util import signals

log = logging.getLogger(__name__)


class DiskUsage(BaseModel):
    total_gb: float
    free_gb: float
    disk_space_low: bool


current_disk_usage = DiskUsage(total_gb=0, free_gb=0, disk_space_low=False)


async def update_disk_space():
    global current_disk_usage
    usage = shutil.disk_usage("/")
    current_disk_usage = DiskUsage(
        total_gb=usage.total / 1024**3,
        free_gb=usage.free / 1024**3,
        disk_space_low=usage.free / 1024**3 < 1,
    )
    signals.on_disk_usage_update.send(current_disk_usage)
