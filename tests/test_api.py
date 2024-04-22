from tests.conftest import requires_test_env


@requires_test_env('full')
async def test_204_has_empty_body(api_client):
	delete_response = await api_client.delete('protected/help/tours')
	assert delete_response.status_code == 204, delete_response.text
	assert delete_response.content == b''
