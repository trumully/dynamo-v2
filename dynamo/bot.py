from __future__ import annotations

from collections.abc import Sequence
from hashlib import blake2b
from logging import DEBUG, ERROR, INFO, getLogger

import apsw
import discord
from async_utils.lru import LRU
from async_utils.waterfall import Waterfall
from discord import InteractionType, app_commands
from discord.abc import Snowflake

from . import _typings as t
from .utils.files import platformdir, resolve_path_with_links
from .utils.logic import to_json

type Interaction = discord.Interaction[Dynamo]


type ACommand = app_commands.Command[t.Any, t.Any, t.Any]
type AppCommandTypes = app_commands.Group | ACommand | app_commands.ContextMenu


class BotExports(t.NamedTuple):
    commands: list[AppCommandTypes] | None = None


class HasExports(t.Protocol):
    exports: BotExports


class PreemptiveBlocked(Exception):
    pass


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
        installs = app_commands.AppInstallationType(user=True, guild=True)

        ctx = app_commands.AppCommandContext
        contexts = ctx(dm_channel=True, guild=True, private_channel=True)
        return cls(
            client,
            fallback_to_global=False,
            allowed_contexts=contexts,
            allowed_installs=installs,
        )

    @t.override
    async def interaction_check(self, interaction: Interaction, /) -> bool:  # noqa: PLR6301
        if await interaction.client.is_blocked(interaction.user.id):
            resp = interaction.response
            if interaction.type is InteractionType.application_command:
                await resp.send_message("Blocked", ephemeral=True)
            else:
                await resp.defer(ephemeral=True)
            return False
        return True

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
        conn: apsw.Connection,
        read_conn: apsw.Connection,
        initial_exts: list[HasExports],
        **kwargs: object,
    ) -> None:
        intents = discord.Intents.none() if intents is None else intents
        super().__init__(*args, intents=intents, **kwargs)
        self.tree = VersionedTree.from_dynamo(self)
        self.conn = conn
        self.read_conn = read_conn
        self.block_cache: LRU[int, bool] = LRU(512)
        self._last_interact_waterfall = Waterfall(10, 100, self.update_last_seen)
        self.initial_exts = initial_exts
        self.logger = getLogger("dynamo")

    async def update_last_seen(self, user_ids: Sequence[int], /) -> None:
        with self.conn:
            self.conn.executemany(
                """
                INSERT INTO discord_users (user_id, last_interaction)
                VALUES (?, CURRENT_TIMESTAMP)
                ON CONFLICT (user_id)
                DO UPDATE SET last_interaction=excluded.last_interaction;
                """,
                ((user_id,) for user_id in user_ids),
            )

    async def on_interaction(self, interaction: Interaction) -> None:
        if not await self.is_blocked(interaction.user.id):
            self._last_interact_waterfall.put(interaction.user.id)

    async def is_blocked(self, user_id: int) -> bool:
        blocked = self.block_cache.get(user_id, None)
        if blocked is not None:
            return blocked

        row = self.read_conn.execute(
            """
            SELECT EXISTS (
                SELECT 1 FROM discord_users
                WHERE user_id=? AND is_blocked LIMIT 1
            );
            """,
            (user_id,),
        ).fetchone()
        assert row is not None, "SELECT EXISTS top level query"
        b: bool = row[0]
        self.block_cache[user_id] = b
        return b

    async def setup_hook(self) -> None:
        for mod in self.initial_exts:
            exports = mod.exports
            if exports.commands:
                for command_obj in exports.commands:
                    self.tree.add_command(command_obj)

        path = platformdir.user_cache_path / "tree.hash"
        path = resolve_path_with_links(path)
        tree_hash = await self.tree.get_hash()
        self.info("discord.setup_hook", "Command tree hash digest: %s", tree_hash.hex())
        with path.open("r+b") as fp:
            data = fp.read()
            if data != tree_hash:
                await self.tree.sync()
                fp.seek(0)
                fp.write(tree_hash)

    async def start(self, token: str, *, reconnect: bool = True) -> None:
        self._last_interact_waterfall.start()
        await super().start(token, reconnect=reconnect)

    async def close(self) -> None:
        await super().close()
        await self._last_interact_waterfall.stop()

    def _log(
        self,
        name: str,
        level: int,
        message: str,
        *args: object,
        exc_info: bool = False,
    ) -> None:
        self.logger.name = name
        self.logger.log(level, message, *args, exc_info=exc_info)

    def debug(self, name: str, message: str, *args: object) -> None:
        self._log(name, DEBUG, message, *args)

    def info(self, name: str, message: str, *args: object) -> None:
        self._log(name, INFO, message, *args)

    def bug(self, name: str, message: str, *args: object) -> None:
        """Log when the **code** is at fault."""
        self._log(name, ERROR, f"BUG: {message}", *args, exc_info=True)

    def error(self, name: str, message: str, *args: object) -> None:
        """Log when the **user** is at fault."""
        self._log(name, ERROR, message, *args, exc_info=True)
