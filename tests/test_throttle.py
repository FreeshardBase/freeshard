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


def test_throttle_per_key_windows_are_independent():
    @throttle(0.1, key=lambda name: name)
    def call_me(name):
        return f"called {name}"

    assert call_me("a") == "called a"
    assert call_me("b") == "called b"
    assert call_me("a") is None
    assert call_me("b") is None


def test_throttle_reset_clears_all_windows():
    @throttle(0.1, key=lambda name: name)
    def call_me(name):
        return f"called {name}"

    assert call_me("a") == "called a"
    assert call_me("a") is None
    call_me.reset()
    assert call_me("a") == "called a"
