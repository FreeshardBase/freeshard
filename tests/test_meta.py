from httpx import AsyncClient


async def test_get_whoareyou(api_client: AsyncClient):
	default_identity = (await api_client.get('protected/identities/default')).json()
	response = await api_client.get('public/meta/whoareyou')
	response.raise_for_status()
	whoareyou = response.json()
	assert whoareyou['domain'][:6].lower() == default_identity['id'][:6].lower()
	assert whoareyou['id'] == default_identity['id']


async def test_get_whoami(api_client: AsyncClient):
	whoami = (await api_client.get('public/meta/whoami')).json()
	assert whoami['type'] == 'anonymous'
