import inspect
import time


def throttle(min_duration: float, key=None):
    """Drop calls that arrive within min_duration of the previous accepted call.

    key maps the call args to a bucket key so each bucket throttles
    independently; key=None (default) uses one global window for the function.
    The wrapper exposes reset() to clear all windows (test hook).
    """

    def decorator_throttle(func):
        last_call: dict = {}

        def is_allowed(*args, **kwargs):
            k = key(*args, **kwargs) if key is not None else None
            now = time.time()
            prev = last_call.get(k)
            if prev is None or prev + min_duration < now:
                last_call[k] = now
                return True
            return False

        if inspect.iscoroutinefunction(func):

            async def wrapper_throttle(*args, **kwargs):
                if is_allowed(*args, **kwargs):
                    return await func(*args, **kwargs)

        else:

            def wrapper_throttle(*args, **kwargs):
                if is_allowed(*args, **kwargs):
                    return func(*args, **kwargs)

        wrapper_throttle.reset = last_call.clear
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
