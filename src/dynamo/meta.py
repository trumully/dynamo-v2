import discord
from discord import app_commands

from ._typings import BotExports
from .bot import DEV_GUILD, Interaction


@app_commands.command(name="setblocked", description="Block or unblock user from bot")
@app_commands.guilds(DEV_GUILD)
@app_commands.describe(user="The user to block or unblock")
async def set_blocked(
    itx: Interaction, user: discord.User | discord.Member, blocked: bool
) -> None:
    blocked_str = "blocked" if blocked else "unblocked"
    await itx.response.defer(ephemeral=True)
    if blocked and await itx.client.is_blocked(user.id):
        await itx.edit_original_response(content=f"{user!s} is already {blocked_str}")
        return
    await itx.client.set_blocked(user.id, blocked)
    await itx.edit_original_response(content=f"{blocked_str.title()} {user!s}")


exports: BotExports = BotExports(dev_commands=[set_blocked])
