from __future__ import annotations

import hashlib
import logging
import math
import time
from collections.abc import Callable, Generator, Mapping
from enum import StrEnum, auto
from functools import partial
from io import BytesIO

import discord
from async_utils.task_cache import lrutaskcache
from discord import app_commands
from discord.app_commands import Transform
from PIL import Image

from . import _typings as t
from .bot import BotExports, Interaction
from .utils.transformers import CleanString
from .utils.wrappers import executor_function

MAX_PERCEIVED = 764.83
MAX_EUCLEDIAN = 441.67

# lower value = more similar
SIMILARITY_CUTOFF = 0.3

EPSILON = 1e-6


log = logging.getLogger(__name__)


hash_kwargs = {"usedforsecurity": False}


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


class EmbedWithFile(t.TypedDict, total=False):
    embed: discord.Embed
    file: discord.File


class Color(discord.Color):
    def perceived_distance_from(self, other: Color) -> float:
        """Uses cmetric formula from `CompuPhase`_:

        Note that `ΔR = R1 - R2`, similarly for green and blue components.

        Formula:
            `ΔC = √((2 + r̄/256) * ΔR² + 4 * ΔG² + (2 + (255 - r̄)/256) * ΔB²)`

        .. _CompuPhase:
            https://www.compuphase.com/cmetric.htm
        """
        r_mean = (self.r + other.r) >> 1
        r, g, b = self._squared_delta(other)
        dist = math.sqrt(
            (((512 * r_mean) * r) >> 8) + 4 * g + (((767 - r_mean) * b) >> 8)
        )
        return dist / MAX_PERCEIVED

    def _squared_delta(self, other: Color) -> Generator[int]:
        delta_r = self.r - other.r
        delta_g = self.g - other.g
        delta_b = self.b - other.b
        return (int(math.pow(x, 2)) for x in (delta_r, delta_g, delta_b))

    def euclidean_distance_from(self, other: Color) -> float:
        return (math.sqrt(sum(self._squared_delta(other)))) / MAX_EUCLEDIAN

    def is_similar_to(self, other: Color) -> bool:
        p_dist = self.perceived_distance_from(other)
        e_dist = self.euclidean_distance_from(other)
        x = self.r + self.g + self.b
        y = other.r + other.g + other.b

        thresh = SIMILARITY_CUTOFF * (1 + abs((x / MAX_PERCEIVED) - (y / MAX_PERCEIVED)))

        return p_dist <= (thresh + EPSILON) and e_dist <= (thresh + EPSILON)

    @classmethod
    async def transform(cls: type[t.Self], itx: Interaction, value: str, /) -> t.Self:
        return t.cast(t.Self, Color.from_str(value))

    @classmethod
    def from_hsl(cls: type[t.Self], hue: float, sat: float, lum: float) -> t.Self:
        # Adapted from https://stackoverflow.com/a/44134328
        # and https://en.wikipedia.org/wiki/HSL_and_HSV#HSL_to_RGB_alternative
        lum /= 100
        a = sat * min(lum, 1 - lum) / 100

        # n = offset for rgb components (r=0, g=8, b=4)
        def f(n: int):
            # hue shift
            # k is split into 12 different angles of 30deg intervals.
            # 0,4,8 are unique and evenly spaced angles for k.
            k = (n + hue / 30) % 12

            color = lum - a * max(min((k - 3, 9 - k, 1)), -1)
            return f"{round(255 * color):x}"

        return t.cast(t.Self, cls.from_str(f"#{f(0)}{f(8)}{f(4)}"))

    @classmethod
    def white(cls: type[t.Self]) -> t.Self:
        return cls(0xF0F0F0)

    @classmethod
    def black(cls: type[t.Self]) -> t.Self:
        return cls.default()


WHITE = Color.white()
BLACK = Color.black()


def generate_pattern(digest: str) -> list[list[bool]]:
    col3 = [int(x, 16) % 2 == 0 for x in digest[:5]]
    col2 = [int(x, 16) % 2 == 0 for x in digest[5:10]]
    col1 = [int(x, 16) % 2 == 0 for x in digest[10:15]]

    return [[col1[i], col2[i], col3[i], col2[i], col1[i]] for i in range(5)]


def remap(value: str, v_min: int, v_max: int, d_min: int, d_max: int) -> float:
    v = int(value, 16)
    return ((v - v_min) * (d_max - d_min)) / ((v_max - v_min) + d_min)


def generate_color(digest: str) -> Color:
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


@executor_function
def identicon_to_img(digest: str, *, foreground: Color, background: Color) -> bytes:
    to_fill = generate_pattern(digest)

    img = Image.new("RGB", (5, 5), background.to_rgb())
    for i in range(5):
        for j in range(5):
            if to_fill[j][i]:
                img.putpixel((i, j), foreground.to_rgb())

    img = img.resize((350, 350), Image.Resampling.NEAREST)  # type: ignore[reportUnknownMemberType]
    result = Image.new("RGB", (420, 420), background.to_rgb())
    result.paste(img, (35, 35))

    buff = BytesIO()
    result.save(buff, format="png")

    buff.seek(0)
    return buff.getvalue()


@lrutaskcache()
async def create_identicon(
    value: str,
    *,
    algorithm: Algorithm,
    foreground: Color | None,
    background: Color,
) -> tuple[bytes, Color]:
    digest = _HASH_ALGO_MAP[algorithm](value.encode()).hexdigest()

    if foreground is None:
        foreground = generate_color(digest)

    img = await identicon_to_img(digest, foreground=foreground, background=background)

    return img, foreground


async def embed_identicon(
    value: str,
    *,
    algorithm: Algorithm,
    foreground: Color | None,
    background: Color,
) -> EmbedWithFile:
    img, foreground = await create_identicon(
        value, algorithm=algorithm, foreground=foreground, background=background
    )

    file = discord.File(BytesIO(img), filename="identicon.png")
    description = f"Generated with **{algorithm.upper()}**"
    embed = discord.Embed(title=value, color=foreground, description=description)
    embed.add_field(name="Primary", value=str(foreground))
    embed.add_field(name="Background", value=str(background))
    embed.set_image(url="attachment://identicon.png")
    return {"embed": embed, "file": file}


@app_commands.command(name="identicon", description="Generate an identicon from a seed")
@app_commands.describe(
    value="Input used to generate icon",
    foreground="RGB or hexcode color for the foreground",
    background="RGB or hexcode color for the background",
    algorithm="Algorithm used, MD5 by default",
    ephemeral="Send privately",
)
async def get_identicon(
    itx: Interaction,
    value: Transform[str, CleanString] | None = None,
    foreground: Color | None = None,
    background: Color = WHITE,
    algorithm: Algorithm = Algorithm.MD5,
    ephemeral: bool = False,
) -> None:
    if value is None:
        value = str(time.monotonic_ns())

    result = await embed_identicon(
        value,
        algorithm=algorithm,
        foreground=foreground,
        background=background,
    )
    await itx.response.send_message(**result, ephemeral=ephemeral)


@app_commands.context_menu(name="Identicon")
async def identicon_context_menu(
    itx: Interaction, user: discord.Member | discord.User
) -> None:
    result = await embed_identicon(
        str(user.id),
        algorithm=Algorithm.MD5,
        foreground=None,
        background=WHITE,
    )
    await itx.response.send_message(**result, ephemeral=True)


exports = BotExports(commands=[get_identicon, identicon_context_menu])
