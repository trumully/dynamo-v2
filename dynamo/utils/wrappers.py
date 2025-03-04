from __future__ import annotations

import asyncio
from collections.abc import Callable
from functools import wraps

from dynamo._type import CoroFn


def executor_function[**P, T](func: Callable[P, T]) -> CoroFn[P, T]:
    """Send sync function to thread."""

    @wraps(func)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
        return await asyncio.to_thread(func, *args, **kwargs)

    return wrapper
