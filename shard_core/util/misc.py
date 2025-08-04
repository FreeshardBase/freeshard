import inspect
import time


def throttle(min_duration: float):
    def decorator_throttle(func):
        last_call = None

        if inspect.iscoroutinefunction(func):

            async def wrapper_throttle(*args, **kwargs):
                nonlocal last_call
                if last_call is None or last_call + min_duration < time.time():
                    last_call = time.time()
                    return await func(*args, **kwargs)

        else:

            def wrapper_throttle(*args, **kwargs):
                nonlocal last_call
                if last_call is None or last_call + min_duration < time.time():
                    last_call = time.time()
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
