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
	response = await api_client.put(
		f'protected/identities/{default_id.id}/avatar',
		files={'file': ('filename.pdf', b'some bytes')}
	)
	assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


async def test_upload_to_unknown_identity(api_client: AsyncClient):
	i = await api_client.get('protected/identities/default')
	default_id = OutputIdentity.parse_obj(i.json())
	wrong_hash_id = 'foobar' + default_id.id[6:]
	response = await api_client.put(
		f'protected/identities/{wrong_hash_id}/avatar',
		files={'file': ('filename.png', b'some bytes')}
	)
	assert response.status_code == status.HTTP_404_NOT_FOUND


async def test_upload_different_filetypes(api_client: AsyncClient):
	i = await api_client.get('protected/identities/default')
	default_id = OutputIdentity.parse_obj(i.json())

	response = await api_client.put(
		f'protected/identities/{default_id.id}/avatar',
		files={'file': ('filename.png', b'some bytes')}
	)
	response.raise_for_status()

	response = await api_client.put(
		f'protected/identities/{default_id.id}/avatar',
		files={'file': ('filename.jpg', b'some bytes')}
	)
	response.raise_for_status()

	avatars_dir = Path(gconf.get('path_root')) / 'core' / 'assets' / 'avatars'
	assert len(list(avatars_dir.iterdir())) == 1


async def test_put_and_get_happy(api_client: AsyncClient):
	i = await api_client.get('protected/identities/default')
	default_id = OutputIdentity.parse_obj(i.json())

	sent_bytes = b'some bytes'
	response = await api_client.put(
		f'protected/identities/{default_id.id}/avatar',
		files={'file': ('filename.png', sent_bytes)}
	)
	response.raise_for_status()

	response = await api_client.get(f'protected/identities/{default_id.id}/avatar')
	response.raise_for_status()
	response_bytes = response.read()
	assert response_bytes == sent_bytes
	assert response.headers['content-type'] == 'image/png'

	response = await api_client.get('public/meta/avatar')
	response.raise_for_status()
	response_bytes = response.read()
	assert response_bytes == sent_bytes
	assert response.headers['content-type'] == 'image/png'


async def test_get_from_missing_identity(api_client: AsyncClient):
	i = await api_client.get('protected/identities/default')
	default_id = OutputIdentity.parse_obj(i.json())
	wrong_hash_id = 'foobar' + default_id.id[6:]

	response = await api_client.get(f'protected/identities/{wrong_hash_id}/avatar')
	assert response.status_code == status.HTTP_404_NOT_FOUND


async def test_get_missing_avatar(api_client: AsyncClient):
	i = await api_client.get('protected/identities/default')
	default_id = OutputIdentity.parse_obj(i.json())

	response = await api_client.get(f'protected/identities/{default_id.id}/avatar')
	assert response.status_code == status.HTTP_404_NOT_FOUND


async def test_delete_avatar_happy(api_client: AsyncClient):
	i = await api_client.get('protected/identities/default')
	default_id = OutputIdentity.parse_obj(i.json())

	sent_bytes = b'some bytes'
	response = await api_client.put(
		f'protected/identities/{default_id.id}/avatar',
		files={'file': ('filename.png', sent_bytes)}
	)
	response.raise_for_status()

	response = await api_client.delete(f'protected/identities/{default_id.id}/avatar')
	response.raise_for_status()

	response = await api_client.get(f'protected/identities/{default_id.id}/avatar')
	assert response.status_code == status.HTTP_404_NOT_FOUND


async def test_delete_from_missing_identity(api_client: AsyncClient):
	i = await api_client.get('protected/identities/default')
	default_id = OutputIdentity.parse_obj(i.json())
	wrong_hash_id = 'foobar' + default_id.id[6:]

	response = await api_client.delete(f'protected/identities/{wrong_hash_id}/avatar')
	assert response.status_code == status.HTTP_404_NOT_FOUND


async def test_delete_missing_avatar(api_client: AsyncClient):
	i = await api_client.get('protected/identities/default')
	default_id = OutputIdentity.parse_obj(i.json())

	response = await api_client.delete(f'protected/identities/{default_id.id}/avatar')
	response.raise_for_status()


async def test_put_and_get_default_avatar_happy(api_client: AsyncClient):
	sent_bytes = b'some bytes'
	response = await api_client.put(
		'protected/identities/default/avatar',
		files={'file': ('filename.png', sent_bytes)}
	)
	response.raise_for_status()

	response = await api_client.get('protected/identities/default/avatar')
	response.raise_for_status()

	response_bytes = response.read()
	assert response_bytes == sent_bytes
	assert response.headers['content-type'] == 'image/png'


async def test_get_missing_default_avatar(api_client: AsyncClient):
	response = await api_client.get('protected/identities/default/avatar')
	assert response.status_code == status.HTTP_404_NOT_FOUND


async def test_delete_default_avatar(api_client: AsyncClient):
	sent_bytes = b'some bytes'
	response = await api_client.put(
		'protected/identities/default/avatar',
		files={'file': ('filename.png', sent_bytes)}
	)
	response.raise_for_status()

	response = await api_client.delete('protected/identities/default/avatar')
	response.raise_for_status()

	response = await api_client.get('protected/identities/default/avatar')
	assert response.status_code == status.HTTP_404_NOT_FOUND
