from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any


async def _aiterclose(iterator: AsyncIterator[Any]) -> None:
    if hasattr(iterator, "__aiterclose__") and callable(iterator.__aiterclose__):
        await iterator.__aiterclose__()


async def process_async_iterable[T](iterator: AsyncIterator[T]) -> list[T]:
    try:
        return [i async for i in iterator]
    finally:
        await _aiterclose(iterator)
