import asyncio
import datetime
import json
import logging
import subprocess
from pathlib import Path
from typing import List

from portal_core.database.database import backups_table
from portal_core.model.backup import BackupReport, BackupStats

log = logging.getLogger(__name__)

COMMAND_TEMPLATE = '''
rclone 
--azureblob-sas-url {sas_token} 
--crypt-password {obscured_password} 
--crypt-remote :azureblob:{container_name} 
sync {directory} :crypt:{container_name}/{directory} 
--stats-log-level NOTICE --stats 1000m --use-json-log
'''

CLEARTEXT_COMMAND_TEMPLATE = '''
rclone 
--azureblob-sas-url {sas_token}
sync {directory} :azureblob:{container_name}/{directory} 
--stats-log-level NOTICE --stats 1000m --use-json-log
'''


async def sync_directories(directories: List[Path], container_name: str, sas_token: str, password: str):
	obscured_password = subprocess.run(
		['rclone', 'obscure', password], capture_output=True, text=True).stdout.strip()
	report = BackupReport(directories=[])

	log.info(f'Syncing directories {directories} to container {container_name}')
	for directory in directories:
		start_time = datetime.datetime.now(datetime.timezone.utc)

		rel_directory = directory.relative_to(Path.cwd())
		command = COMMAND_TEMPLATE.format(
			sas_token=sas_token,
			obscured_password=obscured_password,
			container_name=container_name,
			directory=rel_directory
		)
		process = await asyncio.create_subprocess_exec(
			*command.split(),
			stdout=asyncio.subprocess.PIPE,
			stderr=asyncio.subprocess.PIPE)
		stdout, stderr = await process.communicate()

		end_time = datetime.datetime.now(datetime.timezone.utc)
		stats = json.loads(stderr.decode())['stats']
		report.directories.append(BackupStats(
			directory=str(rel_directory),
			startTime=start_time,
			endTime=end_time,
			**stats,
		))

	with backups_table() as table:
		table.insert(report.dict())
	log.info('Sync done')
