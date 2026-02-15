from __future__ import annotations

from collections import defaultdict

__lazy_modules__: list[str] = ["asyncio"]

import asyncio
import operator
from functools import partial

import discord
from async_utils.corofunc_cache import lrucorocache
from async_utils.lru import TTLLRU
from discord import app_commands, ui
from discord.app_commands import AppCommandContext, Choice, Group

from . import _typing as t
from ._ac import cf_ac_cache_transform
from ._types import ActionRow, BotExports, Container
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
    leaderboard: list[tuple[int, int]]
    leaderboard_pages: list[list[tuple[int, int]]]


async def fetch_channel_pins(channel: discord.TextChannel) -> tuple[int, list[PinnedMessage]]:
    return channel.id, [m async for m in channel.pins()]  # pyright: ignore[reportReturnType]


_pins_lru: TTLLRU[int, dict[int, list[PinnedMessage]]] = TTLLRU(128, 60 * 60 * 12)
_lock = asyncio.Lock()


async def get_pins(category: discord.CategoryChannel) -> dict[int, list[PinnedMessage]]:
    async with _lock:
        existing = _pins_lru.get(category.id, None)
        if existing is not None:
            return existing
        tasks = [fetch_channel_pins(c) for c in category.text_channels]
        gathered = await asyncio.gather(*tasks)
        result = dict(gathered)
        _pins_lru[category.id] = result
        return result


def filter_pins_by_user(target_id: int, pins: dict[int, list[PinnedMessage]]) -> dict[int, list[PinnedMessage]]:
    user_pins = {c_id: [m for m in msgs if m.author.id == target_id] for c_id, msgs in pins.items()}
    return {c_id: msgs for c_id, msgs in user_pins.items() if msgs}


def chunk[T](lst: list[T], size: int) -> list[list[T]]:
    return [lst[i : i + size] for i in range(0, len(lst), size)]


async def get_pin_statistics(target: int, category: discord.CategoryChannel) -> PinnedData:
    pins = await get_pins(category)
    user_pins = filter_pins_by_user(target, pins)
    user_pin_count = sum(len(msgs) for msgs in user_pins.values())
    user_channel_count = len(user_pins)
    total_pin_count = sum(len(msgs) for msgs in pins.values())
    total_channel_count = len(pins)

    leaderboard: dict[int, int] = defaultdict(int)

    for msgs in pins.values():
        for msg in msgs:
            if msg.author:  # should always be present
                leaderboard[msg.author.id] += 1

    # Sort by most pins
    sorted_leaderboard = sorted(leaderboard.items(), key=operator.itemgetter(1), reverse=True)
    leaderboard_pages = chunk(sorted_leaderboard, 10)

    user_best_channel: tuple[int, int] | None = None
    try:
        best_channel = max(user_pins, key=lambda k: len(user_pins[k]))
        best_messages = len(user_pins[best_channel])
        user_best_channel = (best_channel, best_messages)
    except (ValueError, TypeError):
        pass
    except Exception as ex:
        log.exception("Unexpected error when getting pin statistics", exc_info=ex)

    return PinnedData(
        user=user_pins,
        total=pins,
        user_pins=user_pin_count,
        user_channels=user_channel_count,
        user_best_channel=user_best_channel,
        total_pins=total_pin_count,
        total_channels=total_channel_count,
        leaderboard=sorted_leaderboard,
        leaderboard_pages=leaderboard_pages,
    )


class PinsView:
    @classmethod
    async def placeholder(cls, itx: Interaction) -> None:
        c = Container(ui.TextDisplay("<a:_:1286858083552989265>  Loading. Please wait."))
        await itx.edit_original_response(view=ui.LayoutView().add_item(c))

    @classmethod
    async def start(cls, itx: Interaction, target_id: int, category_id: int, *, deferred: bool) -> None:
        await cls.set(itx, target_id, category_id, 0, initial=True, deferred=deferred)

    @classmethod
    async def set(
        cls,
        itx: Interaction,
        target_id: int,
        category_id: int,
        index: int,
        *,
        initial: bool = False,
        deferred: bool = False,
    ) -> None:
        assert itx.guild is not None, "Guild only context"
        edit = itx.edit_original_response if deferred else itx.response.edit_message
        send = edit if deferred else partial(itx.response.send_message, ephemeral=True)

        category: discord.CategoryChannel = itx.guild.get_channel(category_id)  # pyright: ignore[reportAssignmentType]
        data = await get_pin_statistics(target_id, category)

        c = Container(ui.TextDisplay("# Pins All-time Rankings"))

        row = ActionRow(
            ui.UserSelect(
                custom_id="c:pins:" + b2048pack(("user", itx.user.id, target_id, category_id, index)),
                default_values=[discord.SelectDefaultValue(id=target_id, type=discord.SelectDefaultValueType.user)],
            )
        )
        c.add_item(row)

        text = f"- **{data.user_pins}** pins across **{data.user_channels}** channels\n"
        if data.user_best_channel is not None:
            channel, messages = data.user_best_channel
            text += f"- Most pins in a single channel: **{messages}** in <#{channel}>"
        c.add_item(ui.TextDisplay(text))

        c.add_item(ui.Separator(visible=True, spacing=discord.enums.SeparatorSpacing.large))

        text = f"## `{data.total_pins}` pins across `{data.total_channels}` channels\n"
        for i, (user, pins) in enumerate(data.leaderboard_pages[index], start=(index * 10) + 1):
            text += f"{i}. <@{user}> - **{pins}** {'pins' if pins != 1 else 'pin'}\n"

        text += f"\n-# Page: {index + 1} / {len(data.leaderboard_pages)}"
        c.add_item(ui.TextDisplay(text))

        row = ActionRow(
            ui.Button(
                label="<<",
                custom_id="c:pins:" + b2048pack(("last", itx.user.id, target_id, category_id, 0)),
                disabled=index == 0,
            ),
            ui.Button(
                label="<",
                custom_id="c:pins:" + b2048pack(("previous", itx.user.id, target_id, category_id, max(index - 1, 0))),
                disabled=index == 0,
            ),
            ui.Button(
                label=">",
                custom_id="c:pins:"
                + b2048pack(("next", itx.user.id, target_id, category_id, min(index + 1, len(data.leaderboard_pages) - 1))),
                disabled=index == len(data.leaderboard_pages) - 1,
            ),
            ui.Button(
                label=">>",
                custom_id="c:pins:"
                + b2048pack(("last", itx.user.id, target_id, category_id, len(data.leaderboard_pages) - 1)),
                disabled=index == len(data.leaderboard_pages) - 1,
            ),
        )

        view = ui.LayoutView()
        view.add_item(c)

        method = send if initial else edit
        await method(view=view)

    @classmethod
    async def raw_submit(cls, itx: Interaction, data: str) -> None:
        _action, author, target, category, index = b2048unpack(data, tuple[str, int, int, int, int])
        if itx.user.id != author:
            return

        assert itx.data is not None
        values: list[str] = itx.data.get("values", [])
        if values:
            target = int(values[0])

        await itx.response.defer(ephemeral=True)
        if _pins_lru.get(category, None) is None:
            await cls.placeholder(itx)
        await cls.set(itx, target, category, index, deferred=True)


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
