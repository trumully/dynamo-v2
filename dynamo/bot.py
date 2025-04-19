from __future__ import annotations

import datetime
import logging
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
from ._typings import HasExports, RawSubmittable
from .utils.files import platformdir, resolve_path_with_links
from .utils.logic import to_json

type Interaction = discord.Interaction[Dynamo]


log = logging.getLogger(__name__)

MODAL_REGEX = re.compile(r"^m:(.{1,10}):(.*)$", flags=re.DOTALL)


def _hash_payload(payload: list[dict[str, object]]) -> bytes:
    tree_hash = blake2b(
        digest_size=32, person=b"tree", last_node=True, usedforsecurity=False
    )
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
        return cls(
            client,
            fallback_to_global=False,
            allowed_contexts=contexts,
            allowed_installs=installs,
        )

    @t.override
    async def interaction_check(self, itx: Interaction, /) -> bool:  # noqa: PLR6301
        if not await itx.client.is_blocked(itx.user.id):
            return True
        resp = itx.response
        if itx.type is InteractionType.application_command:
            await resp.send_message("Blocked", ephemeral=True)
        else:
            await resp.defer(ephemeral=True)
        return False

    @t.override
    async def on_error(
        self, itx: Interaction, error: app_commands.AppCommandError, /
    ) -> None:
        send = partial(itx.response.send_message, ephemeral=True)
        if isinstance(error, app_commands.CommandOnCooldown):
            fut = discord.utils.utcnow() + datetime.timedelta(seconds=error.retry_after)
            rel_time = discord.utils.format_dt(fut, style="R")
            msg = f"You're on cooldown. Try again in {rel_time}"
            await send(msg)

        await super().on_error(itx, error)

    async def _get_payload(
        self, *, guild: Snowflake | None = None
    ) -> list[dict[str, object]]:
        commands = self._get_all_commands(guild=guild)

        translator = self.translator
        if translator:
            payload = [
                await cmd.get_translated_payload(self, translator) for cmd in commands
            ]
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
        self.tree = VersionedTree.from_dynamo(self)
        self.raw_modal_submits: dict[str, RawSubmittable] = {}
        self.session = session
        self.conn = conn
        self.read_conn = read_conn
        self.block_cache: LRU[int, bool] = LRU(512)
        self.initial_exts = initial_exts

    async def on_interaction(self, itx: Interaction) -> None:
        if itx.type is InteractionType.modal_submit and itx.data is not None:
            custom_id = itx.data.get("custom_id", "")
            if match := MODAL_REGEX.match(custom_id):
                modal_name, data = match.groups()
                if rs := self.raw_modal_submits.get(modal_name):
                    await rs.raw_submit(itx, data)

    async def is_blocked(self, user_id: int) -> bool:
        blocked = self.block_cache.get(user_id, None)
        if blocked is not None:
            return blocked

        b: bool = self.read_conn.execute(
            """
            SELECT EXISTS (
                SELECT 1 FROM users
                WHERE user_id=? AND is_blocked LIMIT 1
            );
            """,
            (user_id,),
        ).get
        assert b is not None, "SELECT EXISTS top level query"
        self.block_cache[user_id] = b
        return b

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

    async def setup_hook(self) -> None:
        for mod in self.initial_exts:
            exports = mod.exports
            if exports.commands:
                for command_obj in exports.commands:
                    self.tree.add_command(command_obj)
            if exports.raw_modal_submits:
                self.raw_modal_submits.update(exports.raw_modal_submits)

        path = platformdir.user_cache_path / "tree.hash"
        path = resolve_path_with_links(path)
        tree_hash = await self.tree.get_hash()
        log.info("Command tree hash digest: %s", tree_hash.hex())
        with path.open("r+b") as fp:
            data = fp.read()
            if data != tree_hash:
                await self.tree.sync()
                fp.seek(0)
                fp.write(tree_hash)
