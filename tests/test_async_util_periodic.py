import asyncio

import pytest

from shard_core.util.async_util import PeriodicTask, CronTask


class Counter:
    def __init__(self):
        self.n = 0

    async def count(self):
        self.n += 1


def test_fail_invalid_cron_expression():
    with pytest.raises(TypeError):
        CronTask(Counter.count, cron="foo")


async def test_delay():
    c = Counter()
    p = PeriodicTask(c.count, delay=1)
    p.start()
    await asyncio.sleep(2)
    p.stop()
    assert c.n == 2


async def test_cron():
    c = Counter()
    p = CronTask(c.count, cron="* * * * * *")
    p.start()
    await asyncio.sleep(2)
    p.stop()
    assert c.n == 2


@requires_test_env("full")
async def test_cron_continues_after_exception():
    """CronTask must keep running after the function raises an exception."""

    class FailOnce:
        def __init__(self):
            self.n = 0

        async def run(self):
            self.n += 1
            if self.n == 1:
                raise RuntimeError("intentional test error")

    f = FailOnce()
    p = CronTask(f.run, cron="* * * * * *")
    p.start()
    await asyncio.sleep(3)
    p.stop()
    # First call raised, but the task should have continued and run at least once more
    assert f.n >= 2
