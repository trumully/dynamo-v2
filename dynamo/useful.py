from __future__ import annotations

import logging
from functools import partial

import discord
from async_utils.corofunc_cache import lrucorocache
from async_utils.lru import LRU
from discord import app_commands
from discord.app_commands import Choice

from ._ac import ac_cache_transform_guild
from ._typings import BotExports
from .bot import Interaction

log = logging.getLogger(__name__)


_guild_event_cache: LRU[int, list[discord.ScheduledEvent]] = LRU(128)


def get_cached_event(guild: discord.Guild, value: int) -> discord.ScheduledEvent | None:
    if _guild_event_cache.get(guild.id, None) is None:
        _guild_event_cache[guild.id] = []

    event = next((e for e in _guild_event_cache[guild.id] if e.id == value), None)
    if event is not None:
        return event

    event = discord.utils.get(guild.scheduled_events, id=value)
    if event is not None:
        _guild_event_cache[guild.id].append(event)

    return event


@app_commands.command(
    name="interested",
    description="Format a scheduled event with a hyperlink and list of attendees",
)
@app_commands.describe(event="The name of the event", ephemeral="Send privately")
@app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
async def interested(itx: Interaction, event: str, ephemeral: bool = True) -> None:
    if itx.guild is None:
        raise app_commands.NoPrivateMessage from None

    # The 'value' of the event from the selected choice is acutally the event ID in string
    # form. Treat it as such here.
    if (event_ := get_cached_event(itx.guild, int(event))) is None:
        await itx.response.send_message("That event does not exist!", ephemeral=True)
        return

    users_interested = " ".join([u.mention async for u in event_.users()])
    content = f"`[{event_.name}]({event_.url}) {users_interested or 'None interested'}`"

    await itx.response.send_message(content=content, ephemeral=ephemeral)


@interested.autocomplete("event")
@lrucorocache(300, cache_transform=ac_cache_transform_guild)
async def event_ac(itx: Interaction, current: str) -> list[Choice[str]]:
    if itx.guild is None:
        return []
    return [
        Choice(name=e.name, value=str(e.id))
        for e in itx.guild.scheduled_events[:25]
        if current in e.name
    ]


@interested.error  # type: ignore[reportUnknownMemberType]
async def interested_error(itx: Interaction, error: app_commands.AppCommandError) -> None:
    send = partial(itx.response.send_message, ephemeral=True)
    if isinstance(error, app_commands.NoPrivateMessage):
        await send("This command cannot be used in direct messages.")


exports = BotExports(commands=[interested])
