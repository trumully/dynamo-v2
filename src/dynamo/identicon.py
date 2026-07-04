from __future__ import annotations

import hashlib
import time
from enum import StrEnum, auto
from functools import partial
from io import BytesIO

import discord
from async_utils.task_cache import lrutaskcache
from discord import app_commands
from PIL import Image

from . import _typings as t
from ._types import BotExports
from .bot import Interaction
from .color import Color, hsl_to_rgb
from .logs import Logger, get_logger
from .utils import afunc

log: Logger = get_logger(__name__)


hash_kwargs: t.Mapping[str, object] = {"usedforsecurity": False}


class Algorithm(StrEnum):
    MD5 = auto()
    SHA1 = auto()
    SHA256 = auto()
    SHA512 = auto()
    BLAKE2B = auto()
    SHA3_256 = auto()
    SHA3_512 = auto()


# fmt: off
_HASH_ALGO_MAP = {
    Algorithm.MD5:      partial(hashlib.md5, **hash_kwargs),
    Algorithm.SHA1:     partial(hashlib.sha1, **hash_kwargs),
    Algorithm.SHA256:   partial(hashlib.sha256, **hash_kwargs),
    Algorithm.SHA512:   partial(hashlib.sha512, **hash_kwargs),
    Algorithm.BLAKE2B:  partial(hashlib.blake2b, **hash_kwargs),
    Algorithm.SHA3_256: partial(hashlib.sha3_256, **hash_kwargs),
    Algorithm.SHA3_512: partial(hashlib.sha3_512, **hash_kwargs)
}
# fmt: on

WHITE = Color(0xF0F0F0)

PIXEL_SIZE = 70
MARGIN = PIXEL_SIZE // 2
GRID_SIZE = 5
WIDTH = HEIGHT = GRID_SIZE * PIXEL_SIZE + MARGIN * 2


def generate_color(data: bytes, /) -> Color:
    h = ((data[12] & 0x0F) << 8) | data[13]

    hue = h * 360 / 4095
    sat = (65.0 - (data[14] * 20 / 255)) / 100
    lum = (75.0 - (data[15] * 20 / 255)) / 100
    return hsl_to_rgb(hue, sat, lum)


def nibbles(data: bytes) -> t.Generator[int]:
    for byte in data:
        yield (byte & 0xF0) >> 4
        yield byte & 0x0F


def digest_to_mask(data: bytes) -> int:
    gen = nibbles(data)
    mask = 0
    for col in range(2, -1, -1):
        for row in range(GRID_SIZE):
            nib = next(gen, 1)
            filled = nib % 2 == 0

            if filled:
                mask |= 1 << (row * GRID_SIZE + col)
                mask |= 1 << (row * GRID_SIZE + (4 - col))
    return mask


def render_identicon(mask: int, fg: tuple[int, int, int], bg: tuple[int, int, int], /) -> bytes:
    stride = WIDTH * 3

    buffer = bytearray(WIDTH * HEIGHT * 3)
    buffer[:] = bg * (WIDTH * HEIGHT)
    fg_row = bytes(list(fg)) * PIXEL_SIZE

    for y in range(GRID_SIZE):
        for x in range(GRID_SIZE):
            bit = y * 5 + x
            if not (mask >> bit) & 1:
                continue

            base_y = (MARGIN + y * PIXEL_SIZE) * stride
            base_x = (MARGIN + x * PIXEL_SIZE) * 3

            for py in range(PIXEL_SIZE):
                start = base_y + py * stride + base_x
                buffer[start : start + PIXEL_SIZE * 3] = fg_row

    return bytes(buffer)


@lrutaskcache(maxsize=1024)
@afunc()
def get_identicon_png_bytes(
    digest: bytes,
    foreground: tuple[int, int, int],
    background: tuple[int, int, int],
) -> bytes:
    mask = digest_to_mask(digest)
    img = Image.frombytes("RGB", (420, 420), render_identicon(mask, foreground, background))
    out = BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


async def generate_identicon(
    digest: bytes,
    foreground: tuple[int, int, int],
    background: tuple[int, int, int],
) -> BytesIO:
    png_bytes = await get_identicon_png_bytes(digest, foreground, background)
    return BytesIO(png_bytes)


async def send_identicon(
    itx: Interaction,
    value: str,
    algorithm: Algorithm,
    foreground: Color | None,
    background: Color,
    ephemeral: bool = True,
    /,
) -> None:
    digest = _HASH_ALGO_MAP[algorithm](value.encode("utf-8")).digest()
    foreground = generate_color(digest) if foreground is None else foreground
    img = await generate_identicon(digest, foreground.to_rgb(), background.to_rgb())
    file = discord.File(img, filename="identicon.png")
    description = f"Generated with **{algorithm.upper()}**"
    embed = discord.Embed(title=value, color=foreground, description=description)
    embed.add_field(name="Primary", value=str(foreground))
    embed.add_field(name="Background", value=str(background))
    embed.set_image(url="attachment://identicon.png")
    await itx.response.send_message(embed=embed, file=file, ephemeral=ephemeral)


@app_commands.command(name="identicon", description="Generate an identicon from a hash")
@app_commands.checks.cooldown(2, 5.0, key=lambda i: i.user.id)
@app_commands.describe(
    value="Input used to generate icon",
    foreground="RGB or hexcode color for the foreground",
    background="RGB or hexcode color for the background",
    algorithm="Algorithm used, MD5 by default",
    ephemeral="Send privately",
)
async def get_identicon(
    itx: Interaction,
    value: str | None = None,
    foreground: Color | None = None,
    background: Color = WHITE,
    algorithm: Algorithm = Algorithm.MD5,
    ephemeral: bool = True,
) -> None:
    value = str(time.monotonic_ns()) if value is None else "".join(c for c in value if c.isalnum())
    await send_identicon(itx, value, algorithm, foreground, background, ephemeral)


@app_commands.context_menu(name="Identicon")
async def identicon_menu(itx: Interaction, user: discord.Member | discord.User) -> None:
    await send_identicon(itx, str(user.id), Algorithm.MD5, None, WHITE)


exports: BotExports = BotExports(commands=[get_identicon, identicon_menu])
