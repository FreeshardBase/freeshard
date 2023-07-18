from fastapi import status
from httpx import AsyncClient

PATH = 'protected/management/resize'


async def test_resize_allowed(api_client: AsyncClient, management_api_mock):
	response = await api_client.put(PATH, json={'size': 'm'})
	response.raise_for_status()
	assert response.status_code == status.HTTP_204_NO_CONTENT


async def test_resize_forbidden(api_client: AsyncClient, management_api_mock):
	response = await api_client.put(PATH, json={'size': 'l'})
	assert response.status_code == status.HTTP_409_CONFLICT
