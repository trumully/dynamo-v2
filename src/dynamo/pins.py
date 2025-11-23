from __future__ import annotations

import discord
from async_utils.corofunc_cache import lrucorocache
from async_utils.task_cache import lrutaskcache
from discord.app_commands import AppCommandContext, Choice, Group

from ._ac import cf_ac_cache_transform
from ._types import BotExports
from .bot import Interaction

ctx = AppCommandContext(guild=True, dm_channel=False, private_channel=False)
pinned_group = Group(name="pinned", description="Review current and historic pin statistics", allowed_contexts=ctx)


@lrutaskcache()
async def get_pins(category: discord.CategoryChannel) -> list[discord.Message]:
    messages: list[discord.Message] = []
    for channel in category.text_channels:
        messages.extend([message async for message in channel.pins()])
    return messages


@pinned_group.command(name="set")
async def pinned_set_historic(itx: Interaction, category: str) -> None:
    """Set the category that historic channels are stored"""
    assert itx.guild is not None, "Guild only command"
    await itx.response.defer(ephemeral=True)
    category_id = int(category)
    actual_category = itx.guild.get_channel(category_id)
    if actual_category is None:
        await itx.edit_original_response(content="That category doesn't exist.")
        return

    with itx.client.conn:
        itx.client.conn.execute(
            """
            INSERT INTO guild_archive_category (guild_id, category_id)
            VALUES (?, ?)
            ON CONFLICT (guild_id)
            DO UPDATE SET category_id=excluded.category_id;
            """,
            (itx.guild_id, category_id),
        )
    await itx.edit_original_response(content=f"Set the historic category to {actual_category.name}")


@pinned_set_historic.autocomplete("category")
@lrucorocache(300, cache_transform=cf_ac_cache_transform)
async def autocomplete(itx: Interaction, current: str, /) -> list[Choice[str]]:
    assert itx.guild is not None, "Guild only transformer."
    cf_current = current.casefold()
    categories = {c for c in itx.guild.categories if c.name.casefold().startswith(cf_current)}
    return [Choice(name=c.name, value=str(c.id)) for c in categories]


exports: BotExports = BotExports(commands=[pinned_group])
