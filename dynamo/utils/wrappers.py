from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from functools import wraps

from dynamo import _typings as t

type Coro[R] = Coroutine[t.Any, t.Any, R]
type CoroFn[**P, R] = Callable[P, Coro[R]]


def executor_function[**P, R](func: Callable[P, R]) -> CoroFn[P, R]:
    """Send sync function to thread."""

    @wraps(func)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        return await asyncio.to_thread(func, *args, **kwargs)

    return wrapper
