import asyncio

import pytest

from shard_core.util.async_util import PeriodicTask, CronTask
from tests.conftest import requires_test_env


class Counter:
	def __init__(self):
		self.n = 0

	async def count(self):
		self.n += 1


@requires_test_env('full')
def test_fail_invalid_cron_expression():
	with pytest.raises(TypeError):
		CronTask(Counter.count, cron='foo')


@requires_test_env('full')
async def test_delay():
	c = Counter()
	p = PeriodicTask(c.count, delay=1)
	p.start()
	await asyncio.sleep(2)
	p.stop()
	assert c.n == 2


@requires_test_env('full')
async def test_cron():
	c = Counter()
	p = CronTask(c.count, cron='* * * * * *')
	p.start()
	await asyncio.sleep(2)
	p.stop()
	assert c.n == 2
