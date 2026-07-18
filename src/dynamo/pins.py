from __future__ import annotations

__lazy_modules__: list[str] = ["asyncio"]

import asyncio
import operator
from collections import Counter
from functools import partial
from itertools import chain

import discord
from async_utils.corofunc_cache import lrucorocache
from discord import app_commands, ui

from . import _typings as t
from ._types import BotExports, DynButton, DynChannelSelect, DynUserSelect
from .bot import Interaction
from .logs import Logger, get_logger
from .utils import b2048pack, b2048unpack, chunk, plural

LEADERBOARD_BATCH = 5

log: Logger = get_logger(__name__)

type ChannelWithPins = discord.VoiceChannel | discord.TextChannel | discord.CategoryChannel


def channel_cache_transform(
    args: tuple[discord.abc.Snowflake], kwds: t.Mapping[str, object]
) -> tuple[tuple[int], t.Mapping[str, object]]:
    return (args[0].id,), kwds


async def get_channel_pins(channel: discord.VoiceChannel | discord.TextChannel, /) -> list[discord.abc.PinnedMessage]:
    return [m async for m in channel.pins(limit=None)]


@lrucorocache(60 * 60, cache_transform=channel_cache_transform)
async def get_pins(channel: ChannelWithPins) -> list[discord.abc.PinnedMessage]:
    pins: list[discord.abc.PinnedMessage]
    if isinstance(channel, discord.CategoryChannel):
        tasks = {get_channel_pins(c) for c in chain(channel.text_channels, channel.voice_channels)}
        pins = list(chain.from_iterable(await asyncio.gather(*tasks)))
    else:
        pins = await get_channel_pins(channel)
    return pins


def get_user_pins_by_channel(user_id: int, pins: list[discord.abc.PinnedMessage]) -> dict[int, int]:
    user_pins = [pin for pin in pins if pin.author.id == user_id]
    if not user_pins:
        return {}
    unique_channels = {pin.channel.id for pin in user_pins}
    if len(unique_channels) == 1:
        return {unique_channels.pop(): len(user_pins)}
    pins_by_channel = {channel: sum(1 for pin in user_pins if pin.channel.id == channel) for channel in unique_channels}
    return dict(sorted(pins_by_channel.items(), key=operator.itemgetter(1), reverse=True))


def get_total_pins_by_user(pins: list[discord.abc.PinnedMessage]) -> dict[int, int]:
    count = Counter(pin.author.id for pin in pins)
    return dict(count.most_common())


def user_pins_by_channel_leaderboard(pins: dict[int, int]) -> list[list[str]]:
    return chunk(
        [f"{i + 1}. <#{channel}> - **`{plural(pin):pin}`**\n" for i, (channel, pin) in enumerate(pins.items())],
        LEADERBOARD_BATCH,
    )


def total_pins_by_user_leaderboard(pins: dict[int, int]) -> list[list[str]]:
    return chunk(
        [f"{i + 1}. <@{user}> - **`{plural(pin):pin}`**\n" for i, (user, pin) in enumerate(pins.items())],
        LEADERBOARD_BATCH,
    )


class PinsView:
    @staticmethod
    def custom_id(*to_pack: object) -> str:
        return "c:pins:" + b2048pack(to_pack)

    @classmethod
    def set_leaderboard(
        cls,
        items: list[list[str]],
        header: str,
        index: int,
        *,
        first_id: str,
        prev_id: str,
        next_id: str,
        last_id: str,
    ) -> tuple[ui.TextDisplay[ui.LayoutView], ui.ActionRow[ui.LayoutView]]:
        length = len(items)
        index %= length
        first_disabled = index == 0
        last_disabled = index == length - 1

        return ui.TextDisplay(f"{header}\n{''.join(items[index])}-# Page: {index + 1} / {length}"), ui.ActionRow(
            DynButton(label="<<", custom_id=first_id, disabled=first_disabled),
            DynButton(label="<", custom_id=prev_id, disabled=first_disabled),
            DynButton(label=">", custom_id=next_id, disabled=last_disabled),
            DynButton(label=">>", custom_id=last_id, disabled=last_disabled),
        )

    @classmethod
    async def warning(cls, itx: Interaction, message: str) -> None:
        container = ui.Container[ui.LayoutView](ui.TextDisplay(message))
        await itx.edit_original_response(view=ui.LayoutView().add_item(container))

    @classmethod
    async def start(cls, itx: Interaction, target_id: int, channel_id: int, *, deferred: bool) -> None:
        await cls.set(itx, target_id, channel_id, 0, 0, initial=True, deferred=deferred)

    @classmethod
    async def set(
        cls,
        itx: Interaction,
        target_id: int,
        channel_id: int,
        user_page_index: int,
        total_page_index: int,
        *,
        initial: bool = False,
        deferred: bool = False,
    ) -> None:
        assert itx.guild is not None, "Guild only context"
        edit = itx.edit_original_response if deferred else itx.response.edit_message
        send = edit if deferred else partial(itx.response.send_message, ephemeral=True)
        method = send if initial else edit

        channel = itx.guild.get_channel(channel_id)
        if channel is None:
            await cls.warning(itx, "That channel or category does not exist.")
            return

        if isinstance(channel, (discord.ForumChannel, discord.StageChannel)):
            await cls.warning(itx, "An invalid channel type has been selected.")
            return

        pins = await get_pins(channel)

        channel_count = len(channel.channels) if isinstance(channel, discord.CategoryChannel) else 1
        total_pins_by_user = get_total_pins_by_user(pins)
        user_pins_by_channel = get_user_pins_by_channel(target_id, pins)

        c = ui.Container[ui.LayoutView]()

        if user_pins_by_channel and channel_count > 1:
            leaderboard = user_pins_by_channel_leaderboard(user_pins_by_channel)
            text, row = cls.set_leaderboard(
                leaderboard,
                f"### <@{target_id}> pins",
                user_page_index,
                first_id=cls.custom_id("c_first", itx.user.id, target_id, channel_id, 0, total_page_index),
                prev_id=cls.custom_id("c_prev", itx.user.id, target_id, channel_id, user_page_index - 1, total_page_index),
                next_id=cls.custom_id("c_next", itx.user.id, target_id, channel_id, user_page_index + 1, total_page_index),
                last_id=cls.custom_id("c_last", itx.user.id, target_id, channel_id, len(leaderboard) - 1, total_page_index),
            )
            c.add_item(text)
            c.add_item(row)
            c.add_item(ui.Separator(visible=True, spacing=discord.enums.SeparatorSpacing.large))

        if total_pins_by_user:
            leaderboard = total_pins_by_user_leaderboard(total_pins_by_user)
            text, row = cls.set_leaderboard(
                leaderboard,
                f"### All pins in <#{channel_id}>",
                total_page_index,
                first_id=cls.custom_id("t_first", itx.user.id, target_id, channel_id, user_page_index, 0),
                prev_id=cls.custom_id("t_prev", itx.user.id, target_id, channel_id, user_page_index, total_page_index - 1),
                next_id=cls.custom_id("t_next", itx.user.id, target_id, channel_id, user_page_index, total_page_index + 1),
                last_id=cls.custom_id("t_last", itx.user.id, target_id, channel_id, user_page_index, len(leaderboard) - 1),
            )
            c.add_item(text)
            c.add_item(row)

            c.add_item(ui.Separator(visible=True, spacing=discord.enums.SeparatorSpacing.large))

        row = ui.ActionRow[ui.LayoutView]()
        c_id = cls.custom_id("user", itx.user.id, target_id, channel_id, user_page_index, total_page_index)
        row.add_item(
            DynUserSelect(
                custom_id=c_id,
                default_values=[discord.SelectDefaultValue(id=target_id, type=discord.SelectDefaultValueType.user)],
            )
        )
        c.add_item(row)

        if user_pins_by_channel:
            text = f"### Has `{plural(sum(pin for pin in user_pins_by_channel.values())):pin}` in"
            if channel_count > 1:
                text += f" `{plural(len(user_pins_by_channel)):channel}` in"
        else:
            text = "### Has no pins yet in"
        c.add_item(ui.TextDisplay(text))

        row = ui.ActionRow[ui.LayoutView]()
        c_id = cls.custom_id("channel", itx.user.id, target_id, channel_id, user_page_index, total_page_index)
        row.add_item(
            DynChannelSelect(
                custom_id=c_id,
                default_values=[discord.SelectDefaultValue(id=channel_id, type=discord.SelectDefaultValueType.channel)],
                channel_types=[discord.ChannelType.text, discord.ChannelType.voice, discord.ChannelType.category],
            )
        )
        c.add_item(row)

        if total_pins_by_user:
            text = f"### Which has `{plural(sum(pin for pin in total_pins_by_user.values())):pin}` overall"
            if channel_count > 1:
                text += f" in `{plural(channel_count):channel}`"
        else:
            text = "### Which has no pins yet"
        c.add_item(ui.TextDisplay(text))

        view = ui.LayoutView()
        view.add_item(c)
        await method(view=view)

    @classmethod
    async def raw_submit(cls, itx: Interaction, data: str) -> None:
        action, author, target, channel, user_page_index, total_page_index = b2048unpack(
            data, tuple[str, int, int, int, int, int]
        )
        if itx.user.id != author:
            return

        assert itx.data is not None
        values: list[str] = itx.data.get("values", [])
        if values:
            if action == "user":
                target = int(values[0])
            else:
                channel = int(values[0])
            user_page_index = 0
            total_page_index = 0

        await itx.response.defer(ephemeral=True)
        await cls.set(itx, target, channel, user_page_index, total_page_index, deferred=True)


@app_commands.command(name="pins", description="Review channel and user pin statistics")
@app_commands.describe(channel="The channel/category checked. Current by default", user="The user checked. You by default")
@app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
async def pins(itx: Interaction, channel: ChannelWithPins | None, user: (discord.Member | discord.User) | None) -> None:
    assert itx.guild is not None, "Guild only command"
    assert itx.channel is not None, "We are in a channel"
    assert isinstance(itx.channel, discord.abc.GuildChannel), "We are not in DMs"
    await itx.response.defer(ephemeral=True)

    if channel is None:
        channel = itx.channel  # pyright: ignore[reportAssignmentType]
    if user is None:
        user = itx.user

    await PinsView.start(itx, user.id, channel.id, deferred=True)  # pyright: ignore[reportOptionalMemberAccess]


exports: BotExports = BotExports(commands=[pins], raw_component_submits={"pins": PinsView})
