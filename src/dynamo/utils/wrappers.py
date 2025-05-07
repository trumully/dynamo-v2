from __future__ import annotations

import asyncio
from collections.abc import Callable
from functools import wraps
from inspect import iscoroutinefunction

from dynamo import _typing_shim as t
from dynamo._typings import CoroFunc
from dynamo.logs import Logger, get_logger

log: Logger = get_logger(__name__)

TYPE_CHECKING = False
if TYPE_CHECKING:

    class CoroDeco(t.Protocol):
        def __call__[**P, R](self, c: Callable[P, R], /) -> CoroFunc[P, R]: ...

else:

    def f__call__[**P, R](self, c: Callable[P, R], /) -> CoroFunc[P, R]: ...  # noqa: ANN001

    type CoroDeco = type("CoroDeco", (t.Protocol,), {"__call__": f__call__})

_WRAP_ASSIGN = ("__module__", "__name__", "__qualname__", "__doc__")


@t.overload
def afunc(*, fast: bool = False) -> CoroDeco: ...
@t.overload
def afunc[**P, R](func: Callable[P, R], /) -> CoroFunc[P, R]: ...
def afunc[**P, R](
    func: Callable[P, R] | None = None, /, *, fast: bool = False
) -> CoroFunc[P, R] | CoroDeco:
    """A decorator for a synchronous function which turns it into an asynchronous function."""

    def wrapper(coro: Callable[P, R], /) -> CoroFunc[P, R]:
        if iscoroutinefunction(coro):
            log.trace("%r is already a coroutine", coro)
            return coro

        @wraps(coro, assigned=_WRAP_ASSIGN)
        async def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
            if fast:
                log.trace("Running %r fast", coro)
                return coro(*args, **kwargs)
            log.trace("Sending %r to thread", coro)
            return await asyncio.to_thread(coro, *args, **kwargs)

        return wrapped

    return t.cast("CoroDeco", wrapper) if func is None else wrapper(func)
