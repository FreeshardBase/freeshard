import time

from shard_core.util.misc import SlidingWindow, throttle


def test_throttle_once():
    @throttle(0.1)
    def call_me():
        return "called"

    assert call_me() == "called"


def test_throttle_twice():
    @throttle(0.1)
    def call_me():
        return "called"

    assert call_me() == "called"
    assert call_me() is None


def test_throttle_with_delay():
    @throttle(0.1)
    def call_me():
        return "called"

    assert call_me() == "called"
    time.sleep(0.2)
    assert call_me() == "called"


def test_throttle_is_per_argument():
    @throttle(0.1)
    def call_me(key):
        return "called"

    # throttling one key must not drop a call for a different key
    assert call_me("a") == "called"
    assert call_me("a") is None
    assert call_me("b") == "called"


def test_sliding_window_grants_up_to_the_limit():
    window = SlidingWindow(limit=2, window=60)

    assert window.try_acquire() is True
    assert window.try_acquire() is True
    assert window.try_acquire() is False


def test_sliding_window_refills_as_the_window_moves():
    """Without the eviction, the limit is a permanent lockout rather than a
    rate — the owner would get five address changes per process, ever."""
    window = SlidingWindow(limit=1, window=0.1)
    assert window.try_acquire() is True
    assert window.try_acquire() is False

    time.sleep(0.15)

    assert window.try_acquire() is True


def test_sliding_window_reset_returns_the_whole_budget():
    window = SlidingWindow(limit=1, window=60)
    window.try_acquire()

    window.reset()

    assert window.try_acquire() is True
