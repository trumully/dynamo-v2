from __future__ import annotations

import hashlib
import time
from functools import lru_cache, partial
from io import BytesIO

import apsw
import discord
from async_utils.lru import LRU
from discord import app_commands, ui
from discord.app_commands import Range
from PIL import Image

from dynamo.utils import b2048pack, b2048unpack

from . import _typing as t
from ._types import ActionRow, BotExports, Container, Section
from .bot import Interaction
from .color import Color
from .logs import Logger, get_logger
from .utils.wrappers import afunc

log: Logger = get_logger(__name__)

WHITE = Color.white()

REPLAY = "\N{CLOCKWISE RIGHTWARDS AND LEFTWARDS OPEN CIRCLE ARROWS}"
SAVE = "\N{FLOPPY DISK}"
TRASH = "\N{WASTEBASKET}\N{VARIATION SELECTOR-16}"


md5 = partial(hashlib.md5, usedforsecurity=False)
_user_identicons_lru: LRU[int, tuple[str, ...]] = LRU(128)
_color_lru: LRU[str, Color] = LRU(128)


@lru_cache
def generate_pattern(digest: str, /) -> list[list[bool]]:
    col3 = [int(x, 16) % 2 == 0 for x in digest[:5]]
    col2 = [int(x, 16) % 2 == 0 for x in digest[5:10]]
    col1 = [int(x, 16) % 2 == 0 for x in digest[10:15]]

    return [[col1[i], col2[i], col3[i], col2[i], col1[i]] for i in range(5)]


@lru_cache
def remap(value: str, v_min: int, v_max: int, d_min: int, d_max: int) -> float:
    v = int(value, 16)
    return ((v - v_min) * (d_max - d_min)) / ((v_max - v_min) + d_min)


@lru_cache
def generate_background(r: int, g: int, b: int) -> Image.Image:
    return Image.new("RGB", (420, 420), (r, g, b))


def generate_color(digest: str, /) -> Color:
    """Calculated from the last 7 nibbles of a hash HHH|SS|LL.

    HHH (0..4095) remapped to a value between (0..360) = hue
    SS (0..255) remapped to a value between (0..20) = saturation, max 65
    LL (0..255) remapped to a value between (0..20) = luminance, max 75
    """
    if c := _color_lru.get(digest, None):
        return c

    color = digest[-7:]

    hue = remap(color[:3], 0, 4095, 0, 360)
    sat = remap(color[3:5], 0, 255, 0, 20)
    lum = remap(color[5:7], 0, 255, 0, 20)
    _color_lru[digest] = color = Color.from_hsl(hue, 65.0 - sat, 75.0 - lum)
    return color


@afunc()
def identicon_to_img(digest: str, foreground: Color, background: Color, /) -> BytesIO:
    to_fill = generate_pattern(digest)

    fg = foreground.to_rgb()
    bg = background.to_rgb()

    buf = bytearray(5 * 5 * 3)
    i = 0

    for row in to_fill:
        for filled in row:
            buf[i : i + 3] = fg if filled else bg
            i += 3

    img = Image.frombytes("RGB", (5, 5), bytes(buf))

    img = img.resize((350, 350), Image.Resampling.NEAREST)  # pyright: ignore[reportUnknownMemberType]
    result = generate_background(*background.to_rgb())
    result.paste(img, (35, 35))

    buff = BytesIO()
    result.save(buff, format="png", optimize=True)
    buff.seek(0)
    return buff


async def get_user_identicons(conn: apsw.Connection, user_id: int) -> tuple[str, ...]:
    if il := _user_identicons_lru.get(user_id, None):
        return il

    identicons = conn.execute(
        """
        SELECT seed FROM identicons
        WHERE user_id = ?
        """,
        (user_id,),
    )

    _user_identicons_lru[user_id] = r = tuple(seed for t in identicons for seed in t)
    return r


class IdenticonView:
    @classmethod
    async def start(cls, itx: Interaction, seed: str, primary: Color | None, *, deferred: bool) -> None:
        digest = md5(seed.encode()).hexdigest()
        primary = generate_color(digest) if primary is None else primary
        await cls.set(itx, seed, primary, deferred=deferred, initial=True)

    @classmethod
    async def set(
        cls,
        itx: Interaction,
        seed: str,
        primary: Color,
        *,
        deferred: bool = False,
        initial: bool = False,
    ) -> None:
        edit = itx.edit_original_response if deferred else itx.response.edit_message
        send = edit if deferred else partial(itx.response.send_message, ephemeral=True)

        digest = md5(seed.encode()).hexdigest()
        image = await identicon_to_img(digest, primary, WHITE)
        file = discord.File(image, filename="identicon.png")

        fetched = await get_user_identicons(itx.client.read_conn, itx.user.id)
        is_saved = seed in fetched

        v = ui.LayoutView(timeout=30)

        v.add_item(ui.MediaGallery(discord.MediaGalleryItem(file)))

        v.add_item(
            Container(
                Section(
                    ui.TextDisplay(content=f"## Seed `{seed}`\n-# Determines the pattern shape and color."),
                    accessory=ui.Button(
                        custom_id="c:idt:" + b2048pack(("generate", seed, itx.user.id, primary.value)),
                        label="Generate",
                        emoji=REPLAY,
                        style=discord.ButtonStyle.blurple,
                    ),
                ),
                ui.Separator(),
                Section(
                    ui.TextDisplay(
                        content=(
                            f"## {'Delete' if is_saved else 'Save'} Pattern\n-# You have {len(fetched)}/25 patterns saved."
                        )
                    ),
                    accessory=ui.Button(
                        custom_id="c:idt:" + b2048pack(("delete" if is_saved else "save", seed, itx.user.id, primary.value)),
                        style=discord.ButtonStyle.red if is_saved else discord.ButtonStyle.green,
                        emoji=TRASH if is_saved else SAVE,
                    ),
                ),
                accent_color=primary,
            )
        )

        method = send if initial else edit
        kwargs: dict[str, t.Any] = {"file": file} if initial else {"attachments": [file]}
        await method(view=v, **kwargs)

    @classmethod
    async def raw_submit(cls, itx: Interaction, data: str) -> None:
        conn = itx.client.conn
        action, seed, user_id, primary = b2048unpack(data, tuple[str, str, int, int])

        if itx.user.id != user_id:
            return

        await itx.response.defer(ephemeral=True)

        new_primary: Color | None = None
        if action == "generate":
            seed = str(time.monotonic_ns())
            digest = md5(seed.encode()).hexdigest()
            new_primary = generate_color(digest)
        elif action in {"save", "delete"}:
            _user_identicons_lru.remove(user_id)
            with conn:
                if action == "save":
                    try:
                        conn.execute(
                            """
                            INSERT INTO identicons (user_id, seed)
                            VALUES (?, ?)
                            """,
                            (user_id, seed),
                        )
                    except apsw.ConstraintError:
                        log.exception("Failed constraint")
                        msg = "You have saved 25 identicon combinations. Remove combinations to add more."
                        await itx.followup.send(content=msg, ephemeral=True)
                        return
                else:
                    conn.execute(
                        """
                        DELETE FROM identicons
                        WHERE user_id = ? AND seed = ?
                        """,
                        (user_id, seed),
                    )

        await cls.set(itx, seed, new_primary or Color(primary), deferred=True)


class SavedIdenticonView:
    @staticmethod
    async def index_setup(items: tuple[str, ...], index: int) -> tuple[Container, discord.File, str, bool, bool, bool]:
        ln = len(items)
        index %= ln
        seed = items[index]
        first_disabled = index == 0
        last_disabled = index == ln - 1
        prev_next_disabled = ln == 1
        digest = md5(seed.encode()).hexdigest()
        color = generate_color(digest)
        image = await identicon_to_img(digest, color, WHITE)
        file = discord.File(image, filename="identicon.png")
        return (
            Container(
                ui.MediaGallery(discord.MediaGalleryItem(file)),
                ui.TextDisplay(content=f"## Seed `{seed}`"),
                ui.TextDisplay(content=f"## Color `{color!s}`"),
                accent_color=color,
            ),
            file,
            seed,
            first_disabled,
            last_disabled,
            prev_next_disabled,
        )

    @classmethod
    async def start(cls, itx: Interaction, user_id: int, *, deferred: bool = False) -> None:
        await cls.edit_to_current_index(itx, user_id, 0, deferred=deferred, initial=True)

    @classmethod
    async def edit_to_current_index(
        cls,
        itx: Interaction,
        user_id: int,
        index: int,
        *,
        deferred: bool = False,
        initial: bool = False,
    ) -> None:
        fetched = await get_user_identicons(itx.client.read_conn, itx.user.id)

        edit = itx.edit_original_response if deferred else itx.response.edit_message
        send = edit if deferred else partial(itx.response.send_message, ephemeral=True)

        if not fetched:
            if initial:
                await send(content="You have no saved identicons.")
            else:
                v = ui.LayoutView(timeout=5)
                v.add_item(ui.TextDisplay(content="You no longer have any saved identicons."))
                await edit(view=v, attachments=[])
            return

        container, file, seed, f_disabled, l_disabled, single = await cls.index_setup(fetched, index)

        v = ui.LayoutView(timeout=30)
        v.add_item(container)
        v.add_item(
            ActionRow(
                ui.Button(
                    label="<<",
                    custom_id="c:idtv:" + b2048pack(("first", user_id, 0, seed)),
                    disabled=f_disabled,
                ),
                ui.Button(
                    label="<",
                    custom_id="c:idtv:" + b2048pack(("previous", user_id, index - 1, seed)),
                    disabled=single or f_disabled,
                ),
                ui.Button(
                    emoji=TRASH,
                    custom_id="c:idtv:" + b2048pack(("delete", user_id, index, seed)),
                    style=discord.ButtonStyle.red,
                ),
                ui.Button(
                    label=">",
                    custom_id="c:idtv:" + b2048pack(("next", user_id, index + 1, seed)),
                    disabled=single or l_disabled,
                ),
                ui.Button(
                    label=">>",
                    custom_id="c:idtv:" + b2048pack(("last", user_id, len(fetched) - 1, seed)),
                    disabled=l_disabled,
                ),
            ),
        )

        method = send if initial else edit
        kwargs: dict[str, t.Any] = {"file": file} if initial else {"attachments": [file]}
        await method(view=v, **kwargs)

    @classmethod
    async def raw_submit(cls, itx: Interaction, data: str) -> None:
        conn = itx.client.conn
        action, user_id, index, seed = b2048unpack(data, tuple[str, int, int, str])

        if itx.user.id != user_id:
            return

        await itx.response.defer(ephemeral=True)
        if action == "delete":
            _user_identicons_lru.remove(user_id)
            with conn:
                conn.execute(
                    """
                    DELETE FROM identicons
                    WHERE user_id = ? AND seed = ?
                    """,
                    (user_id, seed),
                )

        await cls.edit_to_current_index(itx, user_id, index, deferred=True)


identicon_group = app_commands.Group(name="identicon", description="Generate and view saved identicons")


@identicon_group.command(name="generate", description="Generate an identicon from a seed")
@app_commands.describe(
    seed="Affects the pattern and its color if not set",
    primary="Color of the pattern, in the form #<hex> or rgb(<r>, <g>, <b>)",
)
async def get_identicon(itx: Interaction, seed: Range[str, 1, 25] | None = None, primary: Color | None = None) -> None:
    seed = str(time.monotonic_ns()) if seed is None else "".join(c for c in seed if c.isalnum())
    view = IdenticonView()
    await view.start(itx, seed, primary, deferred=False)


@identicon_group.command(name="view", description="View saved identicons")
async def view_identicons(itx: Interaction) -> None:
    view = SavedIdenticonView()
    await view.start(itx, itx.user.id)


@app_commands.context_menu(name="Identicon")
async def identicon_menu(itx: Interaction, user: discord.Member | discord.User) -> None:
    view = IdenticonView()
    await view.start(itx, str(user.id), None, deferred=False)


exports: BotExports = BotExports(
    commands=[identicon_group, identicon_menu], raw_component_submits={"idt": IdenticonView, "idtv": SavedIdenticonView}
)
