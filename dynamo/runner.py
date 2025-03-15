from __future__ import annotations

import asyncio

import discord

from ._type import HasExports


async def main() -> None:
    from . import identicon, useful

    initial_exts: list[HasExports] = [useful, identicon]

    from .bot import Dynamo

    intents = discord.Intents.default()
    intents.members = True
    intents.guild_scheduled_events = True

    client = Dynamo(intents=intents, initial_exts=initial_exts)

    from .utils.files import get_token

    async with client:
        await client.start(get_token())


def run_bot() -> None:
    from .utils.logging import with_logging

    with with_logging():
        asyncio.run(main())
