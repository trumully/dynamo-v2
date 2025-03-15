from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Any, NamedTuple, Protocol

from discord import app_commands

type ACommand = app_commands.Command[Any, Any, Any]
type AppCommandTypes = app_commands.Group | ACommand | app_commands.ContextMenu


class BotExports(NamedTuple):
    commands: list[AppCommandTypes] | None = None


class HasExports(Protocol):
    exports: BotExports


type Coro[T] = Coroutine[object, object, T]
type CoroFn[**P, T] = Callable[P, Coro[T]]
