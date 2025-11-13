from __future__ import annotations

__lazy_modules__: list[str] = ["asyncio"]

import asyncio
from collections.abc import Callable, Coroutine
from functools import wraps
from inspect import iscoroutinefunction

from dynamo import _typing as t
from dynamo.logs import Logger, get_logger

log: Logger = get_logger(__name__)


type Coro[R] = Coroutine[None, None, R]
type CoroFunc[**P, R] = Callable[P, Coro[R]]


TYPE_CHECKING = False
if TYPE_CHECKING:

    class CoroDeco(t.Protocol):
        def __call__[**P, R](self, c: Callable[P, R], /) -> CoroFunc[P, R]: ...

else:

    def f__call__[**P, R](self, c: Callable[P, R], /) -> CoroFunc[P, R]: ...  # noqa: ANN001

    type CoroDeco = type("CoroDeco", (t.Protocol,), {"__call__": f__call__})

_WRAP_ASSIGN = ("__module__", "__name__", "__qualname__", "__doc__")


def afunc(*, fast: bool = False) -> CoroDeco:
    """A decorator for a synchronous function which turns it into an asynchronous function."""

    def wrapper[**P, R](func: Callable[P, R], /) -> CoroFunc[P, R]:
        if iscoroutinefunction(func):
            return func

        @wraps(func, assigned=_WRAP_ASSIGN)
        async def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
            if fast:
                return func(*args, **kwargs)
            return await asyncio.to_thread(func, *args, **kwargs)

        return wrapped

    return wrapper
