from __future__ import annotations

from collections.abc import AsyncIterator

import msgspec

from dynamo import _type_shim as t
from dynamo._type import CoroFn

encoder = msgspec.json.Encoder()
encode = encoder.encode
decoder = msgspec.json.Decoder()


class AiterCloseable(t.Protocol):
    __aitercloseable__: CoroFn[[], None] | None


async def _aiterclose(iterator: AiterCloseable) -> None:
    close_method: CoroFn[[], None] | None = getattr(iterator, "__aiterclose__", None)
    if callable(close_method):
        await close_method()


async def process_async_iterable[T](iterator: AsyncIterator[T]) -> list[T]:
    try:
        return [i async for i in iterator]
    finally:
        await _aiterclose(iterator)  # type: ignore[reportArgumentType]


def to_json(obj: t.Any) -> str:
    return encode(obj).decode("utf-8")
