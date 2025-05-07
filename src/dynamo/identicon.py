from __future__ import annotations

import hashlib
import time
from collections.abc import Callable, Mapping
from enum import StrEnum, auto
from functools import partial
from io import BytesIO

import discord
from async_utils.task_cache import lrutaskcache
from discord import app_commands
from PIL import Image

from . import _typing_shim as t
from ._typings import BotExports
from .bot import Interaction
from .color import Color
from .logs import Logger, get_logger
from .utils.wrappers import afunc

log: Logger = get_logger(__name__)


hash_kwargs: Mapping[str, object] = {"usedforsecurity": False}


class Algorithm(StrEnum):
    MD5 = auto()
    SHA1 = auto()
    SHA256 = auto()
    SHA512 = auto()


class _Hash(t.Protocol):
    def digest(self) -> bytes: ...
    def hexdigest(self) -> str: ...


# fmt: off
_HASH_ALGO_MAP: Mapping[Algorithm, Callable[[bytes], _Hash]] = {
    Algorithm.MD5:      partial(hashlib.md5, **hash_kwargs),
    Algorithm.SHA1:     partial(hashlib.sha1, **hash_kwargs),
    Algorithm.SHA256:   partial(hashlib.sha256, **hash_kwargs),
    Algorithm.SHA512:   partial(hashlib.sha512, **hash_kwargs),
}
# fmt: on


WHITE = Color.white()


def generate_pattern(digest: str, /) -> list[list[bool]]:
    col3 = [int(x, 16) % 2 == 0 for x in digest[:5]]
    col2 = [int(x, 16) % 2 == 0 for x in digest[5:10]]
    col1 = [int(x, 16) % 2 == 0 for x in digest[10:15]]

    return [[col1[i], col2[i], col3[i], col2[i], col1[i]] for i in range(5)]


def remap(value: str, v_min: int, v_max: int, d_min: int, d_max: int) -> float:
    v = int(value, 16)
    return ((v - v_min) * (d_max - d_min)) / ((v_max - v_min) + d_min)


def generate_color(digest: str, /) -> Color:
    """Calculated from the last 7 nibbles of a hash HHH|SS|LL.

    HHH (0..4095) remapped to a value between (0..360) = hue
    SS (0..255) remapped to a value between (0..20) = saturation, max 65
    LL (0..255) remapped to a value between (0..20) = luminance, max 75
    """
    color = digest[-7:]

    hue = remap(color[:3], 0, 4095, 0, 360)
    sat = remap(color[3:5], 0, 255, 0, 20)
    lum = remap(color[5:7], 0, 255, 0, 20)
    return Color.from_hsl(hue, 65.0 - sat, 75.0 - lum)


@lrutaskcache()
@afunc
def identicon_to_img(digest: str, foreground: Color, background: Color, /) -> bytes:
    to_fill = generate_pattern(digest)

    img = Image.new("RGB", (5, 5), background.to_rgb())
    for i in range(5):
        for j in range(5):
            if to_fill[j][i]:
                img.putpixel((i, j), foreground.to_rgb())

    img = img.resize((350, 350), Image.Resampling.NEAREST)  # pyright: ignore[reportUnknownMemberType]
    result = Image.new("RGB", (420, 420), background.to_rgb())
    result.paste(img, (35, 35))

    buff = BytesIO()
    result.save(buff, format="png")

    buff.seek(0)
    return buff.getvalue()


async def send_identicon(
    itx: Interaction,
    value: str,
    algorithm: Algorithm,
    foreground: Color | None,
    background: Color,
    ephemeral: bool = True,
    /,
) -> None:
    digest = _HASH_ALGO_MAP[algorithm](value.encode()).hexdigest()
    if foreground is None:
        foreground = generate_color(digest)
    img = await identicon_to_img(digest, foreground, background)
    log.trace(
        "%s generated (foregound: %s | background: %s) with algorithm %s",
        value,
        str(foreground),
        str(background),
        algorithm.upper(),
    )

    file = discord.File(BytesIO(img), filename="identicon.png")
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
