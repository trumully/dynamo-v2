from __future__ import annotations

from discord import Interaction as DInter
from discord.app_commands import Command, ContextMenu, Group

from . import _typing_shim as t


class RawSubmittableCls(t.Protocol):
    @classmethod
    async def raw_submit(cls, interaction: DInter, data: str) -> object: ...


class RawSubmittableStatic(t.Protocol):
    @staticmethod
    async def raw_submit(interaction: DInter, data: str) -> object: ...


type ACommand = Command[t.Any, t.Any, t.Any]
type AppCommandTypes = Group | ACommand | ContextMenu
type RawSubmittable = RawSubmittableCls | RawSubmittableStatic


class BotExports(t.NamedTuple):
    commands: list[AppCommandTypes] | None = None
    raw_modal_submits: dict[str, type[RawSubmittable]] | None = None


class HasExports(t.Protocol):
    exports: BotExports
