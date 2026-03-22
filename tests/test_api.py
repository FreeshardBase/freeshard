from httpx import AsyncClient


async def test_204_has_empty_body(app_client: AsyncClient):
    delete_response = await app_client.delete("protected/help/tours")
    assert delete_response.status_code == 204, delete_response.text
    assert delete_response.content == b""
