import inspect
import time
from collections import deque


def throttle(min_duration: float):
    """Throttle calls per distinct positional-args key.

    A call whose positional args match one made within the last min_duration
    seconds is dropped (returns None); different args throttle independently, so
    throttling one app's operation never drops another app's call. Keyed on
    positional args only — callers that vary a throttled arg by keyword collapse
    to one key. One entry is retained per distinct args tuple.
    """

    def decorator_throttle(func):
        last_call: dict[tuple, float] = {}

        if inspect.iscoroutinefunction(func):

            async def wrapper_throttle(*args, **kwargs):
                prev = last_call.get(args)
                if prev is None or prev + min_duration < time.time():
                    last_call[args] = time.time()
                    return await func(*args, **kwargs)

        else:

            def wrapper_throttle(*args, **kwargs):
                prev = last_call.get(args)
                if prev is None or prev + min_duration < time.time():
                    last_call[args] = time.time()
                    return func(*args, **kwargs)

        return wrapper_throttle

    return decorator_throttle


class SlidingWindow:
    """Counts attempts in a moving time window, to cap a request rate.

    In-process and shared by every caller of the endpoint it guards. A shard has
    one owner, so splitting the budget per client would only offer an attacker a
    fresh budget per source address.
    """

    def __init__(self, limit: int, window: float):
        self._limit = limit
        self._window = window
        self._attempts: deque[float] = deque()

    def try_acquire(self) -> bool:
        """Take a slot if one is free, reporting whether it was granted.

        Named for the fact that it records: a predicate name invites calling it
        twice to branch, which silently spends two slots.
        """
        now = time.monotonic()
        while self._attempts and self._attempts[0] < now - self._window:
            self._attempts.popleft()
        if len(self._attempts) >= self._limit:
            return False
        self._attempts.append(now)
        return True

    def reset(self):
        self._attempts.clear()


def format_error(e: Exception):
    if str(e):
        return f"{type(e).__name__}: {e}"
    else:
        return type(e).__name__


def str_to_bool(value: str) -> bool:
    value = value.strip().lower()
    if value in {"true", "1", "yes", "on"}:
        return True
    if value in {"false", "0", "no", "off"}:
        return False
    raise ValueError(f"Cannot interpret {value!r} as boolean")
