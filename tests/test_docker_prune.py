import asyncio

import pytest
from httpx import AsyncClient

function_config_override = {'apps': {'pruning': {'schedule': '* * * * * *'}}}


@pytest.mark.config_override(function_config_override)
async def test_docker_prune(api_client: AsyncClient, memory_logger):
	await asyncio.sleep(1)
	assert any(['docker images pruned' in r.msg for r in memory_logger.records])


async def test_not_docker_prune(api_client: AsyncClient, memory_logger):
	await asyncio.sleep(1)
	assert not any(['docker images pruned' in r.msg for r in memory_logger.records])


async def test_docker_prune_manually(api_client: AsyncClient, memory_logger):
	response = await api_client.post('/protected/settings/prune-images')
	assert response.status_code == 200
	assert any(['docker images pruned' in r.msg for r in memory_logger.records])
