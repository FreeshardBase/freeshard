import inspect
import time


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
