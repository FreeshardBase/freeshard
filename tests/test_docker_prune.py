import asyncio

from httpx import AsyncClient

config_override = {'apps': {'pruning': {'schedule': '* * * * * *'}}}


async def test_docker_prune(api_client: AsyncClient, memory_logger):
	await asyncio.sleep(2)
	assert any(['docker images pruned' in r.msg for r in memory_logger.records])
