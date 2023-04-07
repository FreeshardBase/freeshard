import asyncio

import pytest
from portal_core.util.async_util import Periodic

pytest_plugins = ('pytest_asyncio',)


class Counter:
	def __init__(self):
		self.n = 0

	async def count(self):
		self.n += 1


def test_fail_no_time_definition():
	with pytest.raises(TypeError):
		Periodic(Counter.count)


def test_fail_too_many_time_definitions():
	with pytest.raises(TypeError):
		Periodic(Counter.count, delay=10, cron='1 2 3 4 5 6')


def test_fail_invalid_cron_expression():
	with pytest.raises(TypeError):
		Periodic(Counter.count, cron='foo')


@pytest.mark.asyncio
async def test_delay():
	c = Counter()
	p = Periodic(c.count, delay=1)
	p.start()
	await asyncio.sleep(2)
	p.stop()
	assert c.n == 2


@pytest.mark.asyncio
async def test_cron():
	c = Counter()
	p = Periodic(c.count, cron='* * * * * *')
	p.start()
	await asyncio.sleep(2)
	p.stop()
	assert c.n == 2
