from __future__ import annotations

import re
from functools import partial
from typing import TYPE_CHECKING, Any

import discord
from async_utils.lru import LRU
from discord import AppCommandOptionType, app_commands
from discord.app_commands import Transform, Transformer

from dynamo._type import BotExports
from dynamo.utils.logic import process_async_iterable

if TYPE_CHECKING:
    from dynamo.bot import Interaction

ID_REGEX = r"([0-9]{15,20})$"

_guild_events_cache: LRU[int, list[discord.ScheduledEvent]] = LRU(128)


class ScheduledEventTransformer(Transformer["Dynamo"]):  # type: ignore[reportUndefinedVariable]
    @staticmethod
    def set_result(
        result: discord.ScheduledEvent, guild_id: int
    ) -> discord.ScheduledEvent:
        _guild_events_cache.setdefault(guild_id, [])
        _guild_events_cache[guild_id].append(result)
        return result

    async def transform(
        self, interaction: Interaction, value: Any, /
    ) -> discord.ScheduledEvent:
        guild = interaction.guild

        if guild is None:
            msg = "Tried transforming event outside of guild"
            raise app_commands.NoPrivateMessage(msg) from None

        if isinstance(value, str):
            value = value.casefold()

        result: discord.ScheduledEvent | None = None
        if (events := _guild_events_cache.get(guild.id, None)) is not None:
            result = next(
                (e for e in events if e.name.casefold() == value or str(e.id) == value),
                None,
            )

        if (match := re.compile(ID_REGEX).match(value)) and result is None:
            event_id = int(match.group(1))
            result = guild.get_scheduled_event(event_id) if guild else None
            if result is not None:
                return ScheduledEventTransformer.set_result(result, guild.id)
            for g in interaction.client.guilds:
                if (result := g.get_scheduled_event(event_id)) is not None:
                    break

        if result is None:
            raise app_commands.TransformerError(value, self.type, self) from None

        return ScheduledEventTransformer.set_result(result, guild.id)

    @property
    def type(self) -> AppCommandOptionType:
        return AppCommandOptionType.string


@app_commands.guild_only()
@app_commands.command(
    name="interested",
    description="Format a scheduled event with a hyperlink and list of attendees",
)
@app_commands.describe(
    event="The event name or event id", ephemeral="Result is sent privately"
)
async def interested(
    itx: Interaction,
    event: Transform[discord.ScheduledEvent, ScheduledEventTransformer],
    ephemeral: bool = False,
) -> None:
    await itx.response.defer(ephemeral=ephemeral, thinking=True)

    users = await process_async_iterable(event.users())
    users_interested = " ".join(u.mention for u in users) or "No users interested"
    content = f"`[{event.name}]({event.url}) {users_interested}`"

    await itx.followup.send(content=content, ephemeral=ephemeral)


@interested.error  # type: ignore[reportUnknownMemberType]
async def interested_error(itx: Interaction, error: app_commands.AppCommandError) -> None:
    send = partial(itx.response.send_message, ephemeral=True)
    msg = "An unexpected error ocurred. Please try again."
    if isinstance(error, app_commands.TransformerError):
        msg = "That's not a valid scheduled event. Did you enter the correct name or id?"
    if isinstance(error, app_commands.NoPrivateMessage):
        msg = "This command cannot be used outside of a guild context."
    itx.client.bug("useful.interested", msg, error)
    await send(content=msg)


exports = BotExports(commands=[interested])
