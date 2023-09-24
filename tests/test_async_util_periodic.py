import asyncio

import pytest

from portal_core.util.async_util import PeriodicTask, CronTask

pytest_plugins = ('pytest_asyncio',)


class Counter:
	def __init__(self):
		self.n = 0

	async def count(self):
		self.n += 1


def test_fail_invalid_cron_expression():
	with pytest.raises(TypeError):
		CronTask(Counter.count, cron='foo')


@pytest.mark.asyncio
async def test_delay():
	c = Counter()
	p = PeriodicTask(c.count, delay=1)
	p.start()
	await asyncio.sleep(2)
	p.stop()
	assert c.n == 2


@pytest.mark.asyncio
async def test_cron():
	c = Counter()
	p = CronTask(c.count, cron='* * * * * *')
	p.start()
	await asyncio.sleep(2)
	p.stop()
	assert c.n == 2
