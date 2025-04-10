from __future__ import annotations

import logging
from functools import partial

import discord
from discord import app_commands
from discord.app_commands import Transform

from .bot import BotExports, Interaction
from .utils.logic import process_async_iterable
from .utils.transformers import ScheduledEventTransformer

log = logging.getLogger(__name__)


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
    log_ = log.warning
    if isinstance(error, app_commands.TransformerError):
        msg = "That's not a valid event in this guild. Did you enter the correct name or ID?"
    elif isinstance(error, app_commands.NoPrivateMessage):
        msg = "This command cannot be used outside of a guild context."
    else:
        log_ = log.error
    log_("useful.interested", msg)
    await send(content=msg)


exports = BotExports(commands=[interested])
