"""
Parts of this code is adapted from https://github.com/mikeshardmind/salamander-reloaded/blob/c2c104e78d62d676fe9c93eb70ff1b1c150f798c/src/salamander/utils.py
Copyright and license is preserved in compliance with MPLv2

This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at http://mozilla.org/MPL/2.0/.

Copyright (C) 2020 Michael Hall <https://github.com/mikeshardmind>
"""

from __future__ import annotations

__lazy_modules__: list[str] = ["asyncio"]

import asyncio
import os
from functools import wraps
from inspect import iscoroutinefunction
from pathlib import Path

from base2048 import decode, encode
from msgspec import json, msgpack
from platformdirs import PlatformDirs

from . import _typings as t

type Coro[R] = t.Coroutine[None, None, R]
type CoroFunc[**P, R] = t.Callable[P, Coro[R]]


TYPE_CHECKING = False
if TYPE_CHECKING:

    class CoroDeco(t.Protocol):
        def __call__[**P, R](self, c: t.Callable[P, R], /) -> CoroFunc[P, R]: ...

else:

    def f__call__[**P, R](self, c: t.Callable[P, R], /) -> CoroFunc[P, R]: ...  # noqa: ANN001

    type CoroDeco = type("CoroDeco", (t.Protocol,), {"__call__": f__call__})

_WRAP_ASSIGN = ("__module__", "__name__", "__qualname__", "__doc__")


def afunc(*, fast: bool = False) -> CoroDeco:
    """A decorator for a synchronous function which turns it into an asynchronous function."""

    def wrapper[**P, R](func: t.Callable[P, R], /) -> CoroFunc[P, R]:
        if iscoroutinefunction(func):
            return func

        @wraps(func, assigned=_WRAP_ASSIGN)
        async def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
            if fast:
                return func(*args, **kwargs)
            return await asyncio.to_thread(func, *args, **kwargs)

        return wrapped

    return wrapper


dirs: PlatformDirs = PlatformDirs("dynamo", "trumully", roaming=False)


def resolve_path_with_links(path: Path, /, *, folder: bool = False) -> Path:
    try:
        return path.resolve(strict=True)
    except FileNotFoundError:
        path = resolve_path_with_links(path.parent, folder=True) / path.name
        if folder:
            # python default = read/write/traversable (0o777)
            path.mkdir(mode=0o700)
        else:
            # python default = read/writable (0o666)
            path.touch(mode=0o600)
        return path.resolve(strict=True)


ROOT = resolve_path_with_links(Path(__file__).parent.parent.parent, folder=True)


encoder: json.Encoder = json.Encoder()


def to_json(obj: t.Any) -> str:
    return encoder.encode(obj).decode("utf-8")


def b2048pack(o: object, /) -> str:
    return encode(msgpack.encode(o))


def b2048unpack[T](packed: str, type_: type[T], /) -> T:
    return msgpack.decode(decode(packed), type=type_)


def human_join(seq: t.Sequence[str], /, *, delimiter: str = ", ", end: str = "and") -> str:
    if (size := len(seq)) == 0:
        return ""

    if size == 1:
        return seq[0]

    if size == 2:
        return f"{seq[0]} {end} {seq[1]}"

    return delimiter.join(seq[:-1]) + f" {end} {seq[-1]}"


class plural:
    def __init__(self, value: int) -> None:
        self.value: int = value

    def __format__(self, format_spec: str) -> str:
        v = self.value
        skip_value = format_spec.endswith("!")
        if skip_value:
            format_spec = format_spec[:-1]

        singular, _, plural = format_spec.partition("|")
        plural = plural or f"{singular}s"
        if skip_value:
            if abs(v) != 1:
                return plural
            return singular

        if abs(v) != 1:
            return f"{v} {plural}"
        return f"{v} {singular}"


def chunk[T](sequence: list[T], size: int) -> list[list[T]]:
    return [sequence[i : i + size] for i in range(0, len(sequence), size)]


def _get_stored_token() -> str | None:
    token_file_path = dirs.user_config_path / "dynamo.token"
    token_file_path = resolve_path_with_links(token_file_path)
    with token_file_path.open(mode="r", encoding="utf-8") as fp:
        data = fp.read()
        return decode(data).decode("utf-8") if data else None


def get_token() -> str:
    token = os.getenv("DYNAMO_TOKEN") or _get_stored_token()
    if not token:
        msg = "No token? (Use environment `DYNAMO_TOKEN` or launch with `--setup` to go through interactive setup)"
        raise RuntimeError(msg) from None

    return token


def store_token(token: str, /) -> None:
    token_file_path = dirs.user_config_path / "dynamo.token"
    token_file_path = resolve_path_with_links(token_file_path)
    with token_file_path.open(mode="w", encoding="utf-8") as fp:
        fp.write(encode(token.encode()))
