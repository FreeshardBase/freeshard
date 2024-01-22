from pathlib import Path

import gconf
from fastapi import status
from httpx import AsyncClient

from portal_core.model.identity import OutputIdentity


async def test_upload_happy(api_client: AsyncClient):
	i = await api_client.get('protected/identities/default')
	default_id = OutputIdentity.parse_obj(i.json())
	with open('tests/mock_assets/mock_avatar.png', 'rb') as avatar_file:
		response = await api_client.put(
			f'protected/identities/{default_id.id}/avatar',
			files={'file': avatar_file}
		)
	response.raise_for_status()

	uploaded_file_path = Path(gconf.get('path_root')) / 'core' / 'assets' / 'avatars' / f'{default_id.id}.png'
	assert uploaded_file_path.exists()
	with open('tests/mock_assets/mock_avatar.png', 'rb') as avatar_file:
		assert uploaded_file_path.read_bytes() == avatar_file.read()


async def test_upload_wrong_file_type(api_client: AsyncClient):
	i = await api_client.get('protected/identities/default')
	default_id = OutputIdentity.parse_obj(i.json())
	responses = await api_client.put(
		f'protected/identities/{default_id.id}/avatar',
		files={'file': ('filename.pdf', b'some bytes')}
	)
	assert responses.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


async def test_upload_to_unknown_identity(api_client: AsyncClient):
	i = await api_client.get('protected/identities/default')
	default_id = OutputIdentity.parse_obj(i.json())
	wrong_hash_id = 'foobar' + default_id.id[6:]
	responses = await api_client.put(
		f'protected/identities/{wrong_hash_id}/avatar',
		files={'file': ('filename.png', b'some bytes')}
	)
	assert responses.status_code == status.HTTP_404_NOT_FOUND
