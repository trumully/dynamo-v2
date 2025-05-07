from __future__ import annotations

import datetime
import re
from functools import partial
from hashlib import blake2b

import aiohttp
import apsw
import discord
from async_utils.lru import LRU
from discord import InteractionType, app_commands
from discord.abc import Snowflake

from . import _typing_shim as t
from ._config import config
from ._typings import HasExports, RawSubmittable
from .logs import Logger, get_logger
from .utils import dirs, resolve_path_with_links, to_json

type Interaction = discord.Interaction[Dynamo]


DEV_GUILD = discord.Object(config.dev_guild, type=discord.Guild)

log: Logger = get_logger(__name__)

modal_regex: re.Pattern[str] = re.compile(r"^m:(.{1,10}):(.*)$", flags=re.DOTALL)
component_regex: re.Pattern[str] = re.compile(r"^c:(.{1,10}):(.*)$", flags=re.DOTALL)


def _hash_payload(payload: list[dict[str, object]]) -> bytes:
    tree_hash = blake2b(digest_size=32, person=b"tree", last_node=True, usedforsecurity=False)
    command_hashes = [
        blake2b(
            to_json(c).encode(), person=b"command", last_node=False, usedforsecurity=False
        ).digest()
        for c in payload
    ]
    for h in sorted(command_hashes):
        tree_hash.update(h)

    return b"v1:" + tree_hash.digest()


class VersionedTree(app_commands.CommandTree["Dynamo"]):
    @classmethod
    def from_dynamo(cls: type[t.Self], client: Dynamo) -> t.Self:
        installs = app_commands.AppInstallationType(user=False, guild=True)

        ctx = app_commands.AppCommandContext
        contexts = ctx(dm_channel=True, guild=True, private_channel=True)
        log.trace(
            "Got %s with installs %s and contexts %s",
            cls.__qualname__,
            installs.to_array(),
            contexts.to_array(),
        )
        return cls(
            client,
            fallback_to_global=False,
            allowed_contexts=contexts,
            allowed_installs=installs,
        )

    @t.override
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

    @t.override
    async def on_error(self, itx: Interaction, error: app_commands.AppCommandError, /) -> None:
        send = partial(itx.response.send_message, ephemeral=True)
        if isinstance(error, app_commands.CommandOnCooldown):
            fut = discord.utils.utcnow() + datetime.timedelta(seconds=error.retry_after)
            rel_time = discord.utils.format_dt(fut, style="R")
            msg = f"You're on cooldown. Try again in {rel_time}"
            await send(msg)
        elif isinstance(error, app_commands.TransformerError):
            msg = f"`{error.value}` is not valid!"
            await send(msg)
        else:
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
        super().__init__(*args, intents=intents, **kwargs)
        self.tree: VersionedTree = VersionedTree.from_dynamo(self)
        self.raw_modal_submits: dict[str, RawSubmittable] = {}
        self.raw_component_submits: dict[str, RawSubmittable] = {}
        self.session = session
        self.conn = conn
        self.read_conn = read_conn
        self.block_cache: LRU[int, bool] = LRU(512)
        self.initial_exts = initial_exts

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
        log.trace("%s %d", "Blocked" if blocked else "Unblocked", user_id)

    async def versioned_sync(self, filename: str, /, *, guild: Snowflake | None = None) -> None:
        path = dirs.user_cache_path / f"{filename}.hash"
        path = resolve_path_with_links(path)
        tree_hash = await self.tree.get_hash(guild=guild)
        log.info("Command %s hash digest: %s", filename, tree_hash.hex())
        with path.open("r+b") as fp:
            if fp.read() != tree_hash:
                await self.tree.sync(guild=guild)
                log.trace("Synced %s", filename)
                fp.seek(0)
                fp.write(tree_hash)

    async def setup_hook(self) -> None:
        for mod in self.initial_exts:
            exports = mod.exports
            log.trace("Adding exports from %r", mod)
            if exports.commands:
                for command_obj in exports.commands:
                    self.tree.add_command(command_obj)
            if exports.dev_commands:
                for command_obj in exports.dev_commands:
                    self.tree.add_command(command_obj, guild=DEV_GUILD)
            if exports.raw_modal_submits:
                self.raw_modal_submits.update(exports.raw_modal_submits)
            if exports.raw_component_submits:
                self.raw_component_submits.update(exports.raw_component_submits)

        await self.versioned_sync("tree")
        await self.versioned_sync("tree_dev", guild=DEV_GUILD)

    async def close(self) -> None:
        await super().close()
        await self.session.close()
