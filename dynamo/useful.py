from __future__ import annotations

import re
from functools import partial

import discord
from async_utils.lru import LRU
from discord import AppCommandOptionType, app_commands
from discord.app_commands import Transform

from .bot import BotExports, Interaction
from .utils.logic import process_async_iterable
from .utils.transformers import DynamoTransformer

_guild_events_cache: LRU[int, list[discord.ScheduledEvent]] = LRU(128)


class ScheduledEventTransformer(DynamoTransformer):
    """discord.ScheduledEvent transformer adapted from the discord.py converter.

    Lookups are done for the local guild if available. Otherwise, for a DM context,
    lookup is done by the global cache.

    The lookup strategy is as follows (in order):

    1. Lookup by ID.
    2. Lookup by url.
    3. Lookup by name.
    """

    @staticmethod
    def _get_cached(
        values: list[discord.ScheduledEvent], value: str, /
    ) -> discord.ScheduledEvent:
        return next(
            e
            for e in values
            if e.name.casefold() == value.casefold()
            or str(e.id) == value
            or e.url.lower() == value.lower()
        )

    async def transform(self, itx: Interaction, value: str, /) -> discord.ScheduledEvent:
        if itx.guild is None:
            msg = "Tried transforming event outside of guild"
            raise app_commands.NoPrivateMessage(msg) from None

        client = itx.client
        guild: discord.Guild | None = itx.guild
        events = _guild_events_cache.setdefault(guild.id, [])
        result: discord.ScheduledEvent | None = None
        try:
            result = ScheduledEventTransformer._get_cached(events, value)
        except StopIteration:
            client.debug("useful", "%s is not yet cached for guild %d", value, guild.id)
        else:
            client.debug("useful", "%s is already cached for guild %d.", value, guild.id)
            return result

        match = DynamoTransformer._get_id_match(value)

        if match:
            # ID match
            event_id = int(match.group(1))
            result = guild.get_scheduled_event(event_id)
        else:
            pattern = (
                r"https?://(?:(ptb|canary|www)\.)?discord\.com/events/"
                r"(?P<guild_id>[0-9]{15,20})/"
                r"(?P<event_id>[0-9]{15,20})$"
            )
            match = re.match(pattern, value, flags=re.IGNORECASE)
            if match:
                # URL match
                guild = itx.client.get_guild(int(match.group("guild_id")))

                if guild is not None:
                    event_id = int(match.group("event_id"))
                    result = guild.get_scheduled_event(event_id)
            # lookup by name
            else:
                result = discord.utils.get(guild.scheduled_events, name=value)
        if result is None:
            raise app_commands.TransformerError(value, self.type, self) from None

        if not events:
            _guild_events_cache[itx.guild.id] = [result]
        else:
            _guild_events_cache[itx.guild.id].append(result)

        return result

    @property
    def type(self) -> AppCommandOptionType:
        return AppCommandOptionType.string


@app_commands.command(
    name="interested",
    description="Format a scheduled event with a hyperlink and list of attendees",
)
@app_commands.guild_only()
@app_commands.describe(
    event="The name, URL, or ID of the event"
    "Name is case-insensitive. For specifity, use its URL or ID",
    ephemeral="Send privately",
)
async def interested(
    itx: Interaction,
    event: Transform[discord.ScheduledEvent, ScheduledEventTransformer],
    ephemeral: bool = True,
) -> None:
    users = await process_async_iterable(event.users())
    users_interested = " ".join(u.mention for u in users) or "No users interested"
    content = f"`[{event.name}]({event.url}) {users_interested}`"

    await itx.response.send_message(content=content, ephemeral=ephemeral)


@interested.error  # type: ignore[reportUnknownMemberType]
async def interested_error(itx: Interaction, error: app_commands.AppCommandError) -> None:
    send = partial(itx.response.send_message, ephemeral=True)
    msg = "An unexpected error ocurred. Please try again."
    log = itx.client.error
    if isinstance(error, app_commands.TransformerError):
        msg = "That's not a valid event in this guild. Did you enter the correct name or ID?"
    elif isinstance(error, app_commands.NoPrivateMessage):
        msg = "This command cannot be used outside of a guild context."
    else:
        log = itx.client.bug
    log("useful.interested", msg)
    await send(content=msg)


exports = BotExports(commands=[interested])
