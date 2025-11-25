from __future__ import annotations

from functools import partial

import discord
from async_utils.corofunc_cache import lrucorocache
from async_utils.task_cache import lrutaskcache
from discord import app_commands, ui
from discord.app_commands import AppCommandContext, Choice, Group

from . import _typing as t
from ._ac import cf_ac_cache_transform
from ._types import BotExports, DynContainer, DynRow, DynUserSelect
from .bot import Interaction
from .logs import Logger, get_logger
from .utils import b2048pack, b2048unpack

if t.TYPE_CHECKING:
    from datetime import datetime

    class PinnedMessage(discord.Message):
        pinned_at: datetime  # pyright: ignore[reportIncompatibleMethodOverride]
        pinned: t.Literal[True]  # pyright: ignore[reportIncompatibleVariableOverride]


log: Logger = get_logger(__name__)

ctx = AppCommandContext(guild=True, dm_channel=False, private_channel=False)
pinned_group = Group(name="pinned", description="Review current and historic pin statistics", allowed_contexts=ctx)


class PinnedData(t.NamedTuple):
    user: dict[int, list[PinnedMessage]]
    total: dict[int, list[PinnedMessage]]
    user_pins: int
    user_channels: int
    user_best_channel: tuple[int, int] | None
    total_pins: int
    total_channels: int


@lrutaskcache(ttl=3600 * 12)
async def get_pins(category: discord.CategoryChannel) -> dict[int, list[PinnedMessage]]:
    messages: dict[int, list[PinnedMessage]] = {}
    for channel in category.text_channels:
        messages[channel.id] = [message async for message in channel.pins()]  # pyright: ignore[reportArgumentType]
    return messages


def filter_pins_by_user(target_id: int, pins: dict[int, list[PinnedMessage]]) -> dict[int, list[PinnedMessage]]:
    user_pins = {c_id: [m for m in msgs if m.author.id == target_id] for c_id, msgs in pins.items()}
    return {c_id: msgs for c_id, msgs in user_pins.items() if msgs}


class PinsView:
    @staticmethod
    async def setup(target_id: int, category: discord.CategoryChannel) -> PinnedData:
        pins = await get_pins(category)
        user_pins = filter_pins_by_user(target_id, pins)
        user_pin_count = sum(len(msgs) for msgs in user_pins.values())
        user_channel_count = len(user_pins)
        total_pin_count = sum(len(msgs) for msgs in pins.values())
        total_channel_count = len(pins)

        user_best_channel: tuple[int, int] | None
        try:
            best_channel = max(user_pins, key=lambda k: len(user_pins[k]))
            best_messages = len(user_pins[best_channel])
            user_best_channel = (best_channel, best_messages)
        except Exception:  # noqa: BLE001
            user_best_channel = None

        return PinnedData(
            user=user_pins,
            total=pins,
            user_pins=user_pin_count,
            user_channels=user_channel_count,
            user_best_channel=user_best_channel,
            total_pins=total_pin_count,
            total_channels=total_channel_count,
        )

    @classmethod
    async def start(cls, itx: Interaction, target_id: int, category_id: int, *, deferred: bool) -> None:
        await cls.set(itx, target_id, category_id, initial=True, deferred=deferred)

    @classmethod
    async def set(
        cls,
        itx: Interaction,
        target_id: int,
        category_id: int,
        *,
        initial: bool = False,
        deferred: bool = False,
    ) -> None:
        assert itx.guild is not None, "Guild only context"
        edit = itx.edit_original_response if deferred else itx.response.edit_message
        send = edit if deferred else partial(itx.response.send_message, ephemeral=True)

        category: discord.CategoryChannel = itx.guild.get_channel(category_id)  # pyright: ignore[reportAssignmentType]
        data = await cls.setup(target_id, category)

        c = DynContainer()

        text = f"Within **{category.name}**, there are **{data.total_pins}** pins across **{data.total_channels}** channels"

        c.add_item(ui.TextDisplay(text))
        c.add_item(ui.Separator(visible=True, spacing=discord.enums.SeparatorSpacing.large))

        c_id = "c:pins:" + b2048pack((itx.user.id, target_id, category_id))
        user_select = DynUserSelect(
            custom_id=c_id,
            default_values=[discord.SelectDefaultValue(id=target_id, type=discord.SelectDefaultValueType.user)],
        )
        row = DynRow()
        row.add_item(user_select)
        c.add_item(row)

        text = f"- **{data.user_pins}** pins across **{data.user_channels}** channels\n"
        if data.user_best_channel is not None:
            channel, messages = data.user_best_channel
            text += f"- Most pins in a single channel: **{messages}** in <#{channel}>"
        c.add_item(ui.TextDisplay(text))

        view = ui.LayoutView()
        view.add_item(c)

        method = send if initial else edit
        await method(view=view)

    @classmethod
    async def raw_submit(cls, itx: Interaction, data: str) -> None:
        author, target, category = b2048unpack(data, tuple[int, int, int])
        if itx.user.id != author:
            return

        assert itx.data is not None
        values: list[str] = itx.data.get("values", [])
        target = int(values[0])

        await itx.response.defer(ephemeral=True)
        await cls.set(itx, target, category, deferred=True)


@pinned_group.command(name="set")
@app_commands.describe(category="The category the historic channels are stored")
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
            INSERT INTO guilds (guild_id) 
            VALUES (:guild_id)
            ON CONFLICT (guild_id)
            DO NOTHING;

            INSERT INTO guild_archive_category (guild_id, category_id)
            VALUES (:guild_id, :category_id)
            ON CONFLICT (guild_id)
            DO UPDATE SET category_id=excluded.category_id;
            """,
            {"guild_id": itx.guild.id, "category_id": category_id},
        )

    await itx.edit_original_response(content=f"Set the historic category to `{actual_category.name}`")


@pinned_group.command(name="get")
@app_commands.describe(user="The user to check. Leave blank to check yourself")
async def pinned_get(itx: Interaction, user: (discord.Member | discord.User) | None) -> None:
    """Get pin statistics for a given user"""
    assert itx.guild is not None, "Guild only command"
    await itx.response.defer(ephemeral=True)
    target = itx.user.id if user is None else user.id

    assert itx.guild is not None, "Guild only command"
    row: tuple[int] | None = itx.client.read_conn.execute(
        """
        SELECT category_id FROM guild_archive_category
        WHERE guild_id = ? LIMIT 1;
        """,
        (itx.guild.id,),
    ).fetchone()

    if row is None:
        await itx.edit_original_response(content="Category not set for this guild.")
        return

    category_id = row[0]

    category: discord.CategoryChannel | None = itx.guild.get_channel(category_id)  # pyright: ignore[reportAssignmentType]
    if category is None:
        await itx.edit_original_response(content="That category no longer exists. Please set a new category.")
        with itx.client.conn:
            itx.client.conn.execute(
                """
                DELETE FROM guild_archive_category
                WHERE guild_id = ?
                """,
                (itx.guild.id,),
            )
        return

    await PinsView.start(itx, target, category_id, deferred=True)


@pinned_set_historic.autocomplete("category")
@lrucorocache(300, cache_transform=cf_ac_cache_transform)
async def autocomplete(itx: Interaction, current: str, /) -> list[Choice[str]]:
    assert itx.guild is not None, "Guild only transformer."
    cf_current = current.casefold()
    categories = {c for c in itx.guild.categories if c.name.casefold().startswith(cf_current)}
    return [Choice(name=c.name, value=str(c.id)) for c in categories]


exports: BotExports = BotExports(commands=[pinned_group], raw_component_submits={"pins": PinsView})
