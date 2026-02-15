"""
This code is adapted from https://github.com/mikeshardmind/salamander-reloaded/blob/c2c104e78d62d676fe9c93eb70ff1b1c150f798c/src/salamander/_type_stuff.py
Copyright and license is preserved in compliance with MPLv2

This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at https://mozilla.org/MPL/2.0/.

Copyright (C) 2020 Michael Hall <https://github.com/mikeshardmind>
"""

from __future__ import annotations

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


Section = ui.Section[ui.LayoutView]
Container = ui.Container[ui.LayoutView]
ActionRow = ui.ActionRow[ui.LayoutView]

type ACommand = Command[t.Any, t.Any, t.Any]
type AppCommandTypes = Group | ACommand | ContextMenu
type RawSubmittable = RawSubmittableCls | RawSubmittableStatic


class BotExports(t.NamedTuple):
    commands: list[AppCommandTypes] | None = None
    raw_component_submits: dict[str, type[RawSubmittable]] | None = None
    raw_modal_submits: dict[str, type[RawSubmittable]] | None = None


class HasExports(t.Protocol):
    __name__: str
    exports: BotExports
