from __future__ import annotations

from hashlib import blake2b
from logging import ERROR, INFO, getLogger

import discord
from discord import app_commands
from discord.abc import Snowflake

from . import _type_shim as t
from ._type import HasExports
from .utils.files import platformdir, resolve_path_with_links
from .utils.logic import to_json

type Interaction = discord.Interaction[Dynamo]


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
        installs = app_commands.AppInstallationType(user=True, guild=True)

        ctx = app_commands.AppCommandContext
        contexts = ctx(dm_channel=True, guild=True, private_channel=True)
        return cls(
            client,
            fallback_to_global=False,
            allowed_contexts=contexts,
            allowed_installs=installs,
        )

    async def _get_payload(self, *, guild: Snowflake | None = None) -> list[dict[str, object]]:
        commands = self._get_all_commands(guild=guild)

        translator = self.translator
        if translator:
            payload = [
                await command.get_translated_payload(self, translator) for command in commands
            ]
        else:
            payload = [command.to_dict(self) for command in commands]

        return payload

    async def get_hash(self, *, guild: Snowflake | None = None) -> bytes:
        payload = await self._get_payload(guild=guild)
        return _hash_payload(payload)


class Dynamo(discord.AutoShardedClient):
    def __init__(
        self,
        *args: object,
        intents: discord.Intents | None = None,
        initial_exts: list[HasExports],
        **kwargs: object,
    ) -> None:
        intents = intents or discord.Intents.none()
        super().__init__(*args, intents=intents, **kwargs)
        self.tree = VersionedTree.from_dynamo(self)
        self.initial_exts = initial_exts
        self.logger = getLogger("dynamo")

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

    def info(self, name: str, message: str, *args: object) -> None:
        self._log(name, INFO, message, *args)

    def bug(self, name: str, message: str, *args: object) -> None:
        self._log(name, ERROR, f"BUG: {message}", *args, exc_info=True)
