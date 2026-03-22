from shutil import _ntuple_diskusage

from fastapi import status

from shard_core.service import disk
from shard_core.service.disk import DiskUsage


async def test_disk_space_is_reported(app_client):
    # Call update_disk_space directly since there is no background worker in app_client
    await disk.update_disk_space()

    response = await app_client.get("protected/stats/disk")
    assert response.status_code == status.HTTP_200_OK
    disk_usage = DiskUsage.model_validate(response.json())
    assert disk_usage.total_gb > 0
    assert disk_usage.free_gb > 0
    assert disk_usage.disk_space_low is False


async def test_disk_space_is_low(mocker, app_client):
    mocker.patch(
        "shard_core.service.disk.shutil.disk_usage",
        lambda _: _ntuple_diskusage(1024**3, 0, 0),
    )
    # Call update_disk_space directly; no need to wait for background task
    await disk.update_disk_space()

    response = await app_client.get("protected/stats/disk")
    assert response.status_code == status.HTTP_200_OK
    disk_usage = DiskUsage.model_validate(response.json())
    assert disk_usage.disk_space_low is True
