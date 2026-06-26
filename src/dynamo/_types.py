"""
This code is adapted from https://github.com/mikeshardmind/salamander-reloaded/blob/c2c104e78d62d676fe9c93eb70ff1b1c150f798c/src/salamander/_type_stuff.py
Copyright and license is preserved in compliance with MPLv2

This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at https://mozilla.org/MPL/2.0/.

Copyright (C) 2020 Michael Hall <https://github.com/mikeshardmind>
"""

from __future__ import annotations

import apsw
from discord import Interaction as DInter
from discord import ui
from discord.app_commands import Command, ContextMenu, Group

from . import _typings as t


class DynamoLike(t.Protocol):
    conn: apsw.Connection
    read_conn: apsw.Connection


type Coro[T: object = t.Any] = t.Coroutine[None, None, T]


class RawSubmittableCls(t.Protocol):
    @classmethod
    async def raw_submit(cls, interaction: DInter, data: str) -> object: ...


class RawSubmittableStatic(t.Protocol):
    @staticmethod
    async def raw_submit(interaction: DInter, data: str) -> object: ...


class DynButton(ui.Button[ui.LayoutView]):
    async def callback(self, interaction: DInter) -> object: ...


class DynSelect(ui.Select[ui.LayoutView]):
    async def callback(self, interaction: DInter) -> object: ...


class DynUserSelect(ui.UserSelect[ui.LayoutView]):
    async def callback(self, interaction: DInter) -> object: ...


class DynSection(ui.Section[ui.LayoutView]):
    async def callback(self, interaction: DInter) -> object: ...


class DynContainer(ui.Container[ui.LayoutView]):
    async def callback(self, interaction: DInter) -> object: ...


class DynRow(ui.ActionRow[ui.LayoutView]):
    async def callback(self, interaction: DInter) -> object: ...


class DeleteAllDataFunc(t.Protocol):
    def __call__(self, client: DynamoLike, /) -> Coro: ...


class DeleteUserDataFunc(t.Protocol):
    def __call__(self, client: DynamoLike, user_id: int, /) -> Coro: ...


class DeleteGuildDataFunc(t.Protocol):
    def __call__(self, client: DynamoLike, guild_id: int, /) -> Coro: ...


class DeleteMemberDataFunc(t.Protocol):
    def __call__(self, client: DynamoLike, guild_id: int, user_id: int, /) -> Coro: ...


class GetUserDataFunc(t.Protocol):
    def __call__(self, client: DynamoLike, /) -> Coro[bytes]: ...


type ACommand = Command[t.Any, ..., t.Any]
type AppCommandTypes = Group | ACommand | ContextMenu
type RawSubmittable = RawSubmittableCls | RawSubmittableStatic


class BotExports(t.NamedTuple):
    commands: list[AppCommandTypes] | None = None
    raw_component_submits: dict[str, type[RawSubmittable]] | None = None
    raw_modal_submits: dict[str, type[RawSubmittable]] | None = None
    delete_all_data_func: DeleteAllDataFunc | None = None
    delete_user_data_func: DeleteUserDataFunc | None = None
    delete_guild_data_func: DeleteGuildDataFunc | None = None
    delete_member_data_func: DeleteMemberDataFunc | None = None
    get_user_data_func: GetUserDataFunc | None = None


class HasExports(t.Protocol):
    __name__: str
    exports: BotExports
