import pytest
from httpx import AsyncClient

from tests.util import retry_async

function_config_override = {'apps': {'pruning': {'schedule': '* * * * * *'}}}


@pytest.mark.config_override(function_config_override)
async def test_docker_prune(requests_mock, api_client: AsyncClient, memory_logger):
	async def assert_docker_prune():
		assert any(['docker images pruned' in r.msg for r in memory_logger.records])

	await retry_async(assert_docker_prune, 10, 1)


async def test_docker_prune_manually(requests_mock, api_client: AsyncClient, memory_logger):
	response = await api_client.post('/protected/settings/prune-images')
	assert response.status_code == 200
	assert any(['docker images pruned' in r.msg for r in memory_logger.records])
