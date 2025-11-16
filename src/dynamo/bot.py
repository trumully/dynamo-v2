"""
This code is adapted from https://github.com/mikeshardmind/salamander-reloaded/blob/c2c104e78d62d676fe9c93eb70ff1b1c150f798c/src/salamander/bot.py
Copyright and license is preserved in compliance with MPLv2

This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at https://mozilla.org/MPL/2.0/.

Copyright (C) 2020 Michael Hall <https://github.com/mikeshardmind>
"""

from __future__ import annotations

import datetime
import re
from hashlib import blake2b

import aiohttp
import apsw
import discord
from async_utils.lru import LRU
from async_utils.task_cache import taskcache
from discord import InteractionType, app_commands
from discord.abc import Snowflake

from . import _typing as t
from ._types import HasExports, RawSubmittable
from .logs import Logger, get_logger
from .utils import dirs, resolve_path_with_links, to_json

type Interaction = discord.Interaction[Dynamo]


log: Logger = get_logger(__name__)

modal_regex: re.Pattern[str] = re.compile(r"^m:(.{1,10}):(.*)$", flags=re.DOTALL)
component_regex: re.Pattern[str] = re.compile(r"^c:(.{1,10}):(.*)$", flags=re.DOTALL)


def _hash_payload(payload: list[dict[str, object]]) -> bytes:
    tree_hash = blake2b(digest_size=32, person=b"tree", last_node=True, usedforsecurity=False)
    command_hashes = [
        blake2b(to_json(c).encode(), person=b"command", last_node=False, usedforsecurity=False).digest() for c in payload
    ]
    for h in sorted(command_hashes):
        tree_hash.update(h)

    return b"v1:" + tree_hash.digest()


class VersionedTree(app_commands.CommandTree["Dynamo"]):
    @classmethod
    def from_dynamo(cls: type[t.Self], client: Dynamo) -> t.Self:
        installs = app_commands.AppInstallationType(user=False, guild=True)
        contexts = app_commands.AppCommandContext(dm_channel=True, guild=True, private_channel=True)
        return cls(client, fallback_to_global=False, allowed_contexts=contexts, allowed_installs=installs)

    async def interaction_check(self, itx: Interaction, /) -> bool:
        if not await itx.client.is_blocked(itx.user.id):
            return True
        log.trace("%s is blocked", itx.user)
        resp = itx.response
        if itx.type is InteractionType.application_command:
            await resp.send_message("Blocked", ephemeral=True)
        else:
            await resp.defer(ephemeral=True)
        return False

    async def on_error(self, itx: Interaction, error: app_commands.AppCommandError, /) -> None:
        if isinstance(error, app_commands.CommandOnCooldown):
            fut = discord.utils.utcnow() + datetime.timedelta(seconds=error.retry_after)
            rel_time = discord.utils.format_dt(fut, style="R")
            msg = f"You're on cooldown. Try again in {rel_time}"
            await itx.response.send_message(msg, ephemeral=True, delete_after=error.retry_after)
            return

        await super().on_error(itx, error)

    async def _get_payload(self, *, guild: Snowflake | None = None) -> list[dict[str, object]]:
        commands = self._get_all_commands(guild=guild)

        translator = self.translator
        if translator is not None:
            payload = [await cmd.get_translated_payload(self, translator) for cmd in commands]
        else:
            payload = [cmd.to_dict(self) for cmd in commands]

        return payload

    async def get_hash(self, *, guild: Snowflake | None = None) -> bytes:
        payload = await self._get_payload(guild=guild)
        return _hash_payload(payload)


class Dynamo(discord.AutoShardedClient):
    def __init__(
        self,
        *args: object,
        intents: discord.Intents | None = None,
        session: aiohttp.ClientSession,
        conn: apsw.Connection,
        read_conn: apsw.Connection,
        initial_exts: list[HasExports],
        **kwargs: object,
    ) -> None:
        intents = discord.Intents.none() if intents is None else intents
        super().__init__(*args, intents=intents, **kwargs)  # pyright: ignore[reportArgumentType] - unpacked typed dict
        self.tree: VersionedTree = VersionedTree.from_dynamo(self)
        self.raw_modal_submits: dict[str, RawSubmittable] = {}
        self.raw_component_submits: dict[str, RawSubmittable] = {}
        self.session: aiohttp.ClientSession = session
        self.conn: apsw.Connection = conn
        self.read_conn: apsw.Connection = read_conn
        self.block_cache: LRU[int, bool] = LRU[int, bool](512)
        self.initial_exts: list[HasExports] = initial_exts

    @taskcache(3600)
    async def cachefetch_priority_ids(self) -> set[int]:
        app_info = await self.application_info()
        owner = app_info.owner.id
        team = app_info.team
        return {owner, *(t.id for t in team.members)} if team else {owner}

    async def on_interaction(self, itx: Interaction) -> None:
        for kind, regex, mapping in (
            (InteractionType.modal_submit, modal_regex, self.raw_modal_submits),
            (InteractionType.component, component_regex, self.raw_component_submits),
        ):
            if itx.type is kind and itx.data is not None:
                custom_id = itx.data.get("custom_id", "")
                if match := regex.match(custom_id):
                    name, data = match.groups()
                    if rs := mapping.get(name):
                        await rs.raw_submit(itx, data)

    async def is_blocked(self, user_id: int) -> bool:
        if (blocked := self.block_cache.get(user_id, None)) is not None:
            return blocked

        is_blocked: bool = self.read_conn.execute(
            """
            SELECT EXISTS (
                SELECT 1 FROM users
                WHERE user_id=? AND is_blocked LIMIT 1
            );
            """,
            (user_id,),
        ).get
        self.block_cache[user_id] = is_blocked
        return is_blocked

    async def set_blocked(self, user_id: int, blocked: bool) -> None:
        self.block_cache[user_id] = blocked
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO users (user_id, is_blocked)
                VALUES (?, ?)
                ON CONFLICT (user_id)
                DO UPDATE SET is_blocked=excluded.is_blocked
                """,
                (user_id, blocked),
            )
        log.info("%s %d", "Blocked" if blocked else "Unblocked", user_id)

    async def setup_hook(self) -> None:
        for mod in self.initial_exts:
            exports = mod.exports
            if exports.commands:
                for command_obj in exports.commands:
                    self.tree.add_command(command_obj)
            if exports.raw_modal_submits:
                self.raw_modal_submits.update(exports.raw_modal_submits)
            if exports.raw_component_submits:
                self.raw_component_submits.update(exports.raw_component_submits)
            log.trace("Added exports from %s", mod.__name__)

        path = dirs.user_cache_path / "tree.hash"
        path = resolve_path_with_links(path)
        tree_hash = await self.tree.get_hash()
        log.info("Tree hash digest: %s", tree_hash.hex())
        with path.open("r+b") as fp:
            data = fp.read()
            if data != tree_hash:
                await self.tree.sync()
                fp.seek(0)
                fp.write(tree_hash)

    async def close(self) -> None:
        await super().close()
        await self.session.close()
