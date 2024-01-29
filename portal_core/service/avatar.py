import logging
from pathlib import Path

from portal_core.service.assets import avatars_path

log = logging.getLogger(__name__)


def find_avatar_file(hash_id: str) -> Path:
	found_files = list(avatars_path().glob(f'{hash_id}*'))
	if len(found_files) > 1:
		log.warning(f'There are {len(found_files)} avatar images for identity {hash_id[:6]}. Should be 0 or 1.')
	if len(found_files) == 1:
		return found_files[0]
	else:
		raise FileNotFoundError(hash_id)
