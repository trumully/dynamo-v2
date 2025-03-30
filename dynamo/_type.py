from __future__ import annotations

import re
from collections.abc import Callable, Coroutine

from discord import app_commands

from . import _type_shim as t

type ACommand = app_commands.Command[t.Any, t.Any, t.Any]
type AppCommandTypes = app_commands.Group | ACommand | app_commands.ContextMenu


class BotExports(t.NamedTuple):
    commands: list[AppCommandTypes] | None = None


class HasExports(t.Protocol):
    exports: BotExports


type Coro[T] = Coroutine[object, object, T]
type CoroFn[**P, T] = Callable[P, Coro[T]]


_ID_REGEX = re.compile(r"([0-9]{15,20})$")


class DynamoTransformer(app_commands.Transformer["Dynamo"]):  # type: ignore[reportUnknownVariable]
    """Base class for transformers that are used in the Dynamo library.

    This class is a subclass of `app_commands.Transformer` and provides a
    common interface for all transformers in the library. It also provides
    some utility methods for working with transformers.
    """

    @staticmethod
    def _get_id_match(value: str) -> re.Match[str] | None:
        return _ID_REGEX.match(value)

    @staticmethod
    def _get_cached[T](values: list[T], value: str, /) -> T:
        return NotImplemented
