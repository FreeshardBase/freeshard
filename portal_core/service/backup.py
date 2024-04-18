import asyncio
import datetime
import json
import logging
import subprocess
from pathlib import Path
from typing import List

import gconf

from portal_core import database
from portal_core.database.database import backups_table
from portal_core.model.backup import BackupReport, BackupStats, BackupPassphraseLastAccessInfo
from portal_core.util import passphrase as passphrase_util

log = logging.getLogger(__name__)

STORE_KEY_BACKUP_PASSPHRASE = 'backup_passphrase'
STORE_KEY_BACKUP_PASSPHRASE_LAST_ACCESS = 'backup_passphrase_last_access'

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

	dir_stats = []
	overall_start_time = datetime.datetime.now(datetime.timezone.utc)

	log.info(f'Syncing directories {[str(d) for d in directories]} to container {container_name}')
	for directory in directories:
		if not directory.is_dir():
			log.error(f'Directory {directory} does not exist')
			continue

		start_time = datetime.datetime.now(datetime.timezone.utc)

		path_root = Path(gconf.get('path_root'))
		rel_directory = directory.relative_to(path_root)
		command = COMMAND_TEMPLATE.format(
			sas_token=sas_token,
			obscured_password=obscured_passphrase,
			container_name=container_name,
			directory=rel_directory
		)
		process = await asyncio.create_subprocess_exec(
			*command.split(),
			cwd=path_root,
			stdout=asyncio.subprocess.PIPE,
			stderr=asyncio.subprocess.PIPE)
		stdout, stderr = await process.communicate()

		end_time = datetime.datetime.now(datetime.timezone.utc)
		try:
			rclone_result = json.loads(stderr.decode())
		except json.JSONDecodeError:
			log.error(f'Failed to parse rclone output: {stderr.decode()}')
			raise
		rclone_stats = rclone_result['stats']

		dir_stats.append(BackupStats(
			directory=str(rel_directory),
			startTime=start_time,
			endTime=end_time,
			**rclone_stats,
		))

	overall_end_time = datetime.datetime.now(datetime.timezone.utc)

	report = BackupReport(
		directories=dir_stats,
		startTime=overall_start_time,
		endTime=overall_end_time,
	)
	with backups_table() as table:
		table.insert(report.dict())
	log.info('Sync done')


def get_latest_backup_report() -> BackupReport | None:
	with backups_table() as table:
		latest_stats = max(table.all(), key=lambda x: x['endTime'], default=None)
	return BackupReport.parse_obj(latest_stats) if latest_stats else None


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


def get_backup_passphrase(terminal_id: str) -> str:
	passphrase = database.get_value(STORE_KEY_BACKUP_PASSPHRASE)
	last_access_info = BackupPassphraseLastAccessInfo(
		time=datetime.datetime.now(datetime.timezone.utc),
		terminal_id=terminal_id,
	)
	database.set_value(STORE_KEY_BACKUP_PASSPHRASE_LAST_ACCESS, last_access_info.dict())
	return passphrase
