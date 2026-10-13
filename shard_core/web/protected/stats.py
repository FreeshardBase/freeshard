import logging

from fastapi import APIRouter, status

from shard_core.service import disk, metrics
from shard_core.service.app_installation.worker import installation_worker

log = logging.getLogger(__name__)

router = APIRouter(
    prefix="/stats",
)


@router.get("", status_code=status.HTTP_200_OK, response_model=metrics.ShardStats)
async def shard_stats():
    """Shard-level CPU + memory rollup for the Home resource monitor."""
    return metrics.current_shard_stats


@router.get("/disk", status_code=status.HTTP_200_OK, response_model=disk.DiskUsage)
async def disk_usage():
    return disk.current_disk_usage


@router.get("/tasks", status_code=status.HTTP_200_OK)
async def tasks():
    return {
        "installation": {
            "worker": {
                "is_started": installation_worker.is_started,
                "current_task": str(installation_worker.current_task),
            },
            "tasks": [
                str(task) for task in list(installation_worker._task_queue._queue)
            ],
        }
    }
