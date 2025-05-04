from __future__ import annotations

import asyncio
from collections.abc import Callable
from functools import wraps

from dynamo._typings import CoroFunc
from dynamo.logs import Logger, get_logger

_WRAP_ASSIGN = ("__module__", "__name__", "__qualname__", "__doc__")

log: Logger = get_logger(__name__)


def run_in_thread[**P, R](func: Callable[P, R]) -> CoroFunc[P, R]:
    """Send sync function to thread."""

    @wraps(func, assigned=_WRAP_ASSIGN)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        log.trace("Sending %r to thread", func)
        return await asyncio.to_thread(func, *args, **kwargs)

    return wrapper
