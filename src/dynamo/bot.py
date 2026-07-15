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
from async_utils.waterfall import Waterfall
from discord import InteractionType, app_commands
from discord.abc import Snowflake

from . import _typings as t
from ._types import HasExports, RawSubmittable
from .logs import Logger, get_logger
from .services import Services
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

    @t.override
    async def interaction_check(self, interaction: Interaction, /) -> bool:
        guild = interaction.guild
        is_guild_interaction = guild is not None
        is_guild_blocked = is_guild_interaction and await interaction.client.is_guild_blocked(guild.id)
        is_user_blocked = await interaction.client.is_user_blocked(interaction.user.id)
        is_blocked = (is_user_blocked or is_guild_blocked) if is_guild_interaction else is_user_blocked
        if not is_blocked:
            return True

        resp = interaction.response
        if interaction.type is InteractionType.application_command:
            await resp.send_message("You or the current guild is blocked.", ephemeral=True)
        else:
            await resp.defer(ephemeral=True)
        return False

    @t.override
    async def on_error(self, interaction: Interaction, error: app_commands.AppCommandError, /) -> None:
        if isinstance(error, app_commands.CommandOnCooldown):
            fut = discord.utils.utcnow() + datetime.timedelta(seconds=error.retry_after)
            rel_time = discord.utils.format_dt(fut, style="R")
            msg = f"You are on cooldown. Try again in {rel_time}"
            await interaction.response.send_message(msg, ephemeral=True, delete_after=error.retry_after)
            return

        await super().on_error(interaction, error)

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
        connector: aiohttp.BaseConnector | None = None,
    ) -> None:
        intents = discord.Intents.none() if intents is None else intents
        super().__init__(*args, intents=intents, connector=connector)
        self.raw_modal_submits: dict[str, RawSubmittable] = {}
        self.raw_component_submits: dict[str, RawSubmittable] = {}
        self.tree: VersionedTree = VersionedTree.from_dynamo(self)
        self.session: aiohttp.ClientSession = session
        self.conn: apsw.Connection = conn
        self.read_conn: apsw.Connection = read_conn
        self.user_block_cache: LRU[int, bool] = LRU[int, bool](512)
        self.guild_block_cache: LRU[int, bool] = LRU[int, bool](256)
        self.initial_exts: list[HasExports] = initial_exts
        self.services = Services(self.session)
        self._last_interact_waterfall: Waterfall[int] = Waterfall(10, 100, self.update_last_seen)

    async def update_last_seen(self, user_ids: t.Sequence[int], /) -> None:
        with self.conn:
            self.conn.executemany(
                """
                INSERT INTO users (user_id, last_interaction)
                VALUES (?, CURRENT_TIMESTAMP)
                ON CONFLICT (user_id)
                DO UPDATE SET last_interaction=excluded.last_interaction;
                """,
                ((user_id,) for user_id in user_ids),
            )
            await self.prune_old_users()

    async def on_interaction(self, interaction: Interaction) -> None:
        guild_id = 0 if interaction.guild is None else interaction.guild.id
        if not await self.is_user_blocked(interaction.user.id) or await self.is_guild_blocked(guild_id):
            self._last_interact_waterfall.put(interaction.user.id)
        for kind, regex, mapping in (
            (InteractionType.modal_submit, modal_regex, self.raw_modal_submits),
            (InteractionType.component, component_regex, self.raw_component_submits),
        ):
            if interaction.type is kind and interaction.data is not None:
                custom_id = interaction.data.get("custom_id", "")
                if match := regex.match(custom_id):
                    name, data = match.groups()
                    if rs := mapping.get(name):
                        await rs.raw_submit(interaction, data)

    @taskcache(86400)
    async def prune_old_users(self) -> None:
        with self.conn:
            self.conn.execute(
                """
                DELETE FROM users
                WHERE datetime(CURRENT_TIMESTAMP, '-1 year') > last_interaction;
                """
            )

    async def is_user_blocked(self, user_id: int) -> bool:
        blocked = self.user_block_cache.get(user_id, None)
        if blocked is not None:
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
        self.user_block_cache[user_id] = is_blocked
        return is_blocked

    async def set_user_blocked(self, user_id: int, blocked: bool) -> None:
        self.user_block_cache[user_id] = blocked
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

    async def is_guild_blocked(self, guild_id: int) -> bool:
        blocked = self.guild_block_cache.get(guild_id, None)
        if blocked is not None:
            return blocked

        is_blocked: bool = self.read_conn.execute(
            """
            SELECT EXISTS (
                SELECT 1 FROM guilds
                WHERE guild_id=? AND is_blocked LIMIT 1
            );
            """,
            (guild_id,),
        ).get
        self.guild_block_cache[guild_id] = is_blocked
        return is_blocked

    async def set_guild_blocked(self, guild_id: int, blocked: bool) -> None:
        self.guild_block_cache[guild_id] = blocked
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO guilds (guild_id, is_blocked)
                VALUES (?, ?)
                ON CONFLICT (guild_id)
                DO UPDATE SET is_blocked=excluded.is_blocked
                """,
                (guild_id, blocked),
            )

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
            log.debug("Added exports from %s", mod.__name__)

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

    async def start(self, token: str, *, reconnect: bool = True) -> None:
        self._last_interact_waterfall.start()
        return await super().start(token, reconnect=reconnect)

    async def close(self) -> None:
        await super().close()
        await self._last_interact_waterfall.stop()
        await self.session.close()
