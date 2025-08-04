from asyncio import sleep
from shutil import _ntuple_diskusage

from fastapi import status

from shard_core.service.disk import DiskUsage
from tests.conftest import requires_test_env


@requires_test_env("full")
async def test_disk_space_is_reported(api_client):
    response = await api_client.get("protected/stats/disk")
    assert response.status_code == status.HTTP_200_OK
    disk_usage = DiskUsage.parse_obj(response.json())
    assert disk_usage.total_gb > 0
    assert disk_usage.free_gb > 0
    assert disk_usage.disk_space_low is False


@requires_test_env("full")
async def test_disk_space_is_low(mocker, api_client):
    mocker.patch(
        "shard_core.service.disk.shutil.disk_usage",
        lambda _: _ntuple_diskusage(1024**3, 0, 0),
    )
    # wait till the disk space is updated after the patch takes effect
    await sleep(4)

    response = await api_client.get("protected/stats/disk")
    assert response.status_code == status.HTTP_200_OK
    disk_usage = DiskUsage.parse_obj(response.json())
    assert disk_usage.disk_space_low is True
