from __future__ import annotations

from dataclasses import dataclass, field

from discord import Interaction as DInter
from discord import ui
from discord.app_commands import Command, ContextMenu, Group

from . import _typing as t


class RawSubmittableCls(t.Protocol):
    @classmethod
    async def raw_submit(cls, interaction: DInter, data: str) -> object: ...


class RawSubmittableStatic(t.Protocol):
    @staticmethod
    async def raw_submit(interaction: DInter, data: str) -> object: ...


class DynButton(ui.Button[ui.View]): ...


class DynSelect(ui.Select[ui.View]): ...


type ACommand = Command[t.Any, t.Any, t.Any]
type AppCommandTypes = Group | ACommand | ContextMenu
type RawSubmittable = RawSubmittableCls | RawSubmittableStatic


@dataclass(slots=True)
class BotExports:
    commands: list[AppCommandTypes] = field(default_factory=list)
    dev_commands: list[AppCommandTypes] = field(default_factory=list)
    raw_component_submits: dict[str, type[RawSubmittable]] = field(default_factory=dict)
    raw_modal_submits: dict[str, type[RawSubmittable]] = field(default_factory=dict)


class HasExports(t.Protocol):
    __name__: str
    exports: BotExports
