from __future__ import annotations

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
