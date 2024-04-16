import asyncio
import datetime
import json
import logging
import subprocess
from pathlib import Path
from typing import List

from portal_core import database
from portal_core.database.database import backups_table
from portal_core.model.backup import BackupReport, BackupStats
from portal_core.util import passphrase as passphrase_util

log = logging.getLogger(__name__)

STORE_KEY_BACKUP_PASSPHRASE = 'backup_passphrase'

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


async def sync_directories(directories: List[Path], container_name: str, sas_token: str):
	passphrase = database.get_value(STORE_KEY_BACKUP_PASSPHRASE)
	obscured_passphrase = subprocess.run(
		['rclone', 'obscure', passphrase], capture_output=True, text=True).stdout.strip()
	report = BackupReport(directories=[])

	log.info(f'Syncing directories {directories} to container {container_name}')
	for directory in directories:
		start_time = datetime.datetime.now(datetime.timezone.utc)

		rel_directory = directory.relative_to(Path.cwd())
		command = COMMAND_TEMPLATE.format(
			sas_token=sas_token,
			obscured_password=obscured_passphrase,
			container_name=container_name,
			directory=rel_directory
		)
		# todo: use subprocess util
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


def ensure_packup_passphrase():
	try:
		database.get_value(STORE_KEY_BACKUP_PASSPHRASE)
	except KeyError:
		passphrase_numbers = passphrase_util.generate_passphrase_numbers(10)
		passphrase = passphrase_util.get_passphrase(passphrase_numbers)
		database.set_value(STORE_KEY_BACKUP_PASSPHRASE, passphrase)
		log.info('Generated new backup passphrase')
	else:
		log.info('Backup passphrase already exists')
