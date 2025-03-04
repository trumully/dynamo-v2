from __future__ import annotations

import asyncio

import discord

from ._type import HasExports


async def _run_bot() -> None:
    from . import identicon, useful

    initial_exts: list[HasExports] = [useful, identicon]

    from .bot import Dynamo

    intents = discord.Intents.default()

    intents.members = True

    intents.guild_scheduled_events = True

    client = Dynamo(intents=intents, initial_exts=initial_exts)

    from .utils.files import get_token

    try:
        async with client:
            await client.start(get_token())
    finally:
        if not client.is_closed():
            await client.close()


def run_bot() -> None:
    from .utils.logging import with_logging

    with with_logging():
        asyncio.run(_run_bot())
