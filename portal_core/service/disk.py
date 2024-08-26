import logging
import shutil

log = logging.getLogger(__name__)

disk_space_low = False
total_gb = 0
free_gb = 0


async def update_disk_space():
	global disk_space_low, total_gb, free_gb
	usage = shutil.disk_usage('/')
	total_gb = usage.total / 1024 ** 3
	free_gb = usage.free / 1024 ** 3
	disk_space_low = free_gb < 1
