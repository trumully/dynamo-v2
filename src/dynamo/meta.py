from __future__ import annotations

import discord
from discord import app_commands

from ._types import BotExports
from .bot import DEV_GUILD, Interaction


@app_commands.command(name="setblocked", description="Block or unblock user from bot")
@app_commands.guilds(DEV_GUILD)
@app_commands.describe(user="The user to block or unblock")
async def set_blocked(itx: Interaction, user: discord.User | discord.Member, blocked: bool) -> None:
    if user.id in await itx.client.cachefetch_priority_ids():
        await itx.response.send_message("Cannot modify member of application team", ephemeral=True)
        return

    blocked_str = "blocked" if blocked else "unblocked"
    if blocked is await itx.client.is_blocked(user.id):
        await itx.response.send_message(f"{user!s} is already {blocked_str}", ephemeral=True)
        return
    await itx.client.set_blocked(user.id, blocked)
    await itx.response.send_message(f"{blocked_str.title()} {user!s}", ephemeral=True)


exports: BotExports = BotExports(dev_commands=[set_blocked])
