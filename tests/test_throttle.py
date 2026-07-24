import time

from shard_core.util.misc import throttle


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
