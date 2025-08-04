from fastapi import status
from httpx import AsyncClient

from tests.conftest import requires_test_env

PATH = "protected/management/resize"


@requires_test_env("full")
async def test_resize_allowed(requests_mock, api_client: AsyncClient):
    response = await api_client.put(PATH, json={"size": "m"})
    response.raise_for_status()
    assert response.status_code == status.HTTP_204_NO_CONTENT


@requires_test_env("full")
async def test_resize_forbidden(requests_mock, api_client: AsyncClient):
    response = await api_client.put(PATH, json={"size": "l"})
    assert response.status_code == status.HTTP_409_CONFLICT
