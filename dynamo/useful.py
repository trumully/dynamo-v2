from __future__ import annotations

import re
from functools import partial
from typing import TYPE_CHECKING

import discord
from async_utils.lru import LRU
from discord import AppCommandOptionType, app_commands
from discord.app_commands import Transform, Transformer

from dynamo._type import BotExports
from dynamo.utils.logic import process_async_iterable

if TYPE_CHECKING:
    from .bot import Interaction

ID_REGEX = r"([0-9]{15,20})$"
URL_REGEX = r"https?://(?:(ptb|canary|www)\.)?discord\.com/events/(?P<guild_id>[0-9]{15,20})/(?P<event_id>[0-9]{15,20})$"

_guild_events_cache: LRU[int, list[discord.ScheduledEvent]] = LRU(128)


class ScheduledEventTransformer(Transformer["Dynamo"]):  # type: ignore[reportUnknownVariable]
    async def transform(self, interaction: Interaction, value: str, /) -> discord.ScheduledEvent:
        if interaction.guild is None:
            msg = "Tried transforming event outside of guild"
            raise app_commands.NoPrivateMessage(msg) from None

        # By default we want case-insensitive. On the case there are events with the same name,
        # The user should just use the event ID / link instead.
        value = value.casefold()
        itx_guild: discord.Guild = interaction.guild
        client = interaction.client
        guilds = client.guilds

        events: list[discord.ScheduledEvent] = _guild_events_cache.setdefault(itx_guild.id, [])
        result = next((e for e in events if e.name == value or str(e.id) == value), None)

        if result is not None:
            client.info(
                "useful.interested", "%s is already cached for guild %d.", value, itx_guild.id
            )
            return result

        client.info("useful.interested", "%s is not yet cached for guild %d", value, itx_guild.id)

        if match := re.compile(ID_REGEX).match(value):
            event_id = int(match.group(1))
            result = itx_guild.get_scheduled_event(event_id)
            if result is None:
                result = next((g.get_scheduled_event(event_id) for g in guilds), None)
        if match := re.match(URL_REGEX, value, flags=re.IGNORECASE):
            guild = interaction.client.get_guild(int(match.group("guild_id")))
            if guild is not None:
                result = guild.get_scheduled_event(int(match.group("event_id")))
        else:
            result = discord.utils.get(itx_guild.scheduled_events, name=value)
            if result is None:
                result = next(
                    (discord.utils.get(g.scheduled_events, name=value) for g in guilds),
                    None,
                )

        if result is None:
            raise app_commands.TransformerError(value, self.type, self) from None

        _guild_events_cache[itx_guild.id].append(result)
        return result

    @property
    def type(self) -> AppCommandOptionType:
        return AppCommandOptionType.string


@app_commands.command(
    name="interested",
    description="Format a scheduled event with a hyperlink and list of attendees",
)
@app_commands.guild_only
@app_commands.describe(
    event="The name, URL, or Id of the event. "
    "Name is case-insensitive. For specifity, use its URL or Id.",
    ephemeral="Send privately.",
)
async def interested(
    itx: Interaction,
    event: Transform[discord.ScheduledEvent, ScheduledEventTransformer],
    ephemeral: bool = False,
) -> None:
    users = await process_async_iterable(event.users())
    users_interested = " ".join(u.mention for u in users) or "No users interested"
    content = f"`[{event.name}]({event.url}) {users_interested}`"

    await itx.response.send_message(content=content, ephemeral=ephemeral)


@interested.error  # type: ignore[reportUnknownMemberType]
async def interested_error(itx: Interaction, error: app_commands.AppCommandError) -> None:
    send = partial(itx.response.send_message, ephemeral=True)
    msg = "An unexpected error ocurred. Please try again."
    if isinstance(error, app_commands.TransformerError):
        msg = "That's not a valid event in this guild. Did you enter the correct name or id?"
    if isinstance(error, app_commands.NoPrivateMessage):
        msg = "This command cannot be used outside of a guild context."
    itx.client.bug("useful.interested", msg)
    await send(content=msg)


exports = BotExports(commands=[interested])
