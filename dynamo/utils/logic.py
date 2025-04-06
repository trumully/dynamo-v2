from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Coroutine

import msgspec

from dynamo import _typings as t

encoder = msgspec.json.Encoder()
encode = encoder.encode
decoder = msgspec.json.Decoder()

type Coro[R] = Coroutine[t.Any, t.Any, R]
type CoroFn[**P, R] = Callable[P, Coro[R]]


class AiterCloseable(t.Protocol):
    __aitercloseable__: CoroFn[[], None] | None


async def _aiterclose(iterator: AiterCloseable) -> None:
    close_method: CoroFn[[], None] | None = getattr(iterator, "__aiterclose__", None)
    if close_method is not None:
        await close_method()


async def process_async_iterable[T](iterator: AsyncIterator[T]) -> list[T]:
    try:
        return [i async for i in iterator]
    finally:
        await _aiterclose(iterator)  # type: ignore[reportArgumentType]


def to_json(obj: t.Any) -> str:
    return encode(obj).decode("utf-8")
