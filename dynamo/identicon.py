from __future__ import annotations

import logging
import math
import os
import random
from collections.abc import Sequence
from io import BytesIO

import discord
from async_utils.task_cache import lrutaskcache
from discord import app_commands
from PIL import Image

from . import _typings as t
from .bot import BotExports, Interaction
from .utils.wrappers import executor_function

IDENTICON_SIZE = 500

type Matrix[T] = Sequence[Sequence[T]]


MAX_PERCEIVED = 764.83
MAX_EUCLEDIAN = 441.67

# lower value = more similar
SIMILARITY_CUTOFF = 0.3

EPSILON = 1e-6

log = logging.getLogger(__name__)


class Color(discord.Color):
    def perceived_distance_from(self, other: discord.Color) -> float:
        """Uses cmetric formula from `CompuPhase`_:

        Note that `ΔR = R1 - R2`, similarly for green and blue components.

        Formula:
            `ΔC = √((2 + r̄/256) * ΔR² + 4 * ΔG² + (2 + (255 - r̄)/256) * ΔB²)`

        .. _CompuPhase:
            https://www.compuphase.com/cmetric.htm
        """
        r_mean = (self.r + other.r) >> 1
        # delta of r, g, b each is squared
        color_delta = (self.r - other.r, self.g - other.g, self.b - other.b)
        r, g, b = (x**2 for x in color_delta)
        distance = math.sqrt((((512 * r_mean) * r) >> 8) + 4 * g + (((767 - r_mean) * b) >> 8))
        return distance / MAX_PERCEIVED

    def euclidean_distance_from(self, other: Color) -> float:
        color_delta = (self.r - other.r, self.g - other.g, self.b - other.b)
        return (math.sqrt(sum(x**2 for x in color_delta))) / MAX_EUCLEDIAN

    def is_similar_to(self, other: Color) -> bool:
        p_dist = self.perceived_distance_from(other)
        e_dist = self.euclidean_distance_from(other)
        x = sum((self.r, self.g, self.b))
        y = sum((other.r, other.g, other.b))

        thresh = SIMILARITY_CUTOFF * (1 + abs((x / MAX_PERCEIVED) - (y / MAX_PERCEIVED)))

        return p_dist <= (thresh + EPSILON) and e_dist <= (thresh + EPSILON)

    @classmethod
    async def transform(cls: type[t.Self], itx: Interaction, value: str, /) -> t.Self:
        return t.cast(t.Self, Color.from_str(value))

    @classmethod
    def from_random(cls: type[t.Self]) -> t.Self:
        return cls.from_rgb(random.randint(0, 255), random.randint(0, 255), random.randint(0, 255))

    @classmethod
    def white(cls: type[t.Self]) -> t.Self:
        return cls(0xFFFFFF)

    @classmethod
    def black(cls: type[t.Self]) -> t.Self:
        return cls.default()


WHITE = Color.white()
BLACK = Color.black()


def make_matrix(seed: int, size: int = 4) -> Matrix[int]:
    random.seed(seed)
    width, height = size, size * 2
    result = [([0] * width) for _ in range(height)]
    for i in range(height):
        for j in range(width):
            is_colored = round(random.random(), 2)
            if is_colored <= 0.42:
                result[i][j] = 1

    # flip
    for i in range(height):
        result[i].extend(result[i][::-1])

    return result


def cycle_similar_color(relative_color: Color, *, color_to_change: Color) -> Color:
    """Get a different color that is not similar to the given color."""
    while color_to_change.is_similar_to(relative_color):
        color_to_change = Color.from_random()
    return color_to_change


def get_foreground_color(seed: int, background: Color) -> Color:
    random.seed(seed)
    foreground = Color.from_random()
    return cycle_similar_color(background, color_to_change=foreground)


def color_matrix(matrix: Matrix[int], foreground: Color, background: Color) -> Matrix[Color]:
    width, height = len(matrix[0]), len(matrix)
    colored: Matrix[Color] = [[foreground] * width for _ in range(height)]
    for i in range(height):
        for j in range(width):
            colored[i][j] = foreground if matrix[i][j] == 1 else background

    return colored


@executor_function
def identicon_as_bytes(matrix: Matrix[Color]) -> bytes:
    buffer = BytesIO()

    matrix_width, matrix_height = len(matrix[0]), len(matrix)

    image: Image.Image = Image.new("RGB", (matrix_width, matrix_height), 255)
    for i in range(matrix_height):
        for j in range(matrix_width):
            r, g, b = matrix[i][j].to_rgb()
            image.putpixel((i, j), (r, g, b))

    image = image.resize((IDENTICON_SIZE, IDENTICON_SIZE), Image.Resampling.NEAREST)  # type: ignore[reportUnknownMemberType]
    image = image.rotate(90, Image.Resampling.NEAREST)
    image.save(buffer, format="png")

    buffer.seek(0)
    return buffer.getvalue()


@lrutaskcache()
async def create_identicon(
    seed: int, foreground: Color | None, background: Color
) -> tuple[Color, bytes]:
    matrix = make_matrix(seed)
    if foreground is None:
        foreground = get_foreground_color(seed, background)
    colors = color_matrix(matrix, foreground, background)
    idt_bytes = await identicon_as_bytes(colors)
    return foreground, idt_bytes


async def embed_identicon(
    seed: int,
    title: str,
    foreground: Color | None,
    background: Color,
) -> tuple[discord.Embed, discord.File]:
    foreground, idt_bytes = await create_identicon(seed, foreground, background)

    file = discord.File(BytesIO(idt_bytes), filename="identicon.png")
    embed = discord.Embed(title=title, color=foreground)
    embed.set_image(url="attachment://identicon.png")
    return embed, file


@app_commands.command(name="identicon", description="Generate an identicon from a seed")
@app_commands.describe(
    value="Input used to generate icon",
    foreground="RGB or hexcode color for the foreground",
    background="RGB or hexcode color for the background",
    ephemeral="Send privately",
)
async def get_identicon(
    itx: Interaction,
    value: str | None = None,
    foreground: Color | None = None,
    background: Color = WHITE,
    ephemeral: bool = False,
) -> None:
    try:
        seed = int(value)  # type: ignore[reportArgumentType]
    except (ValueError, TypeError):
        seed_bytes = os.urandom(8) if value is None or not value else value.encode()
        seed = int.from_bytes(seed_bytes, "big")
    title = value or str(seed)

    embed, file = await embed_identicon(seed, title, foreground, background)
    await itx.response.send_message(embed=embed, file=file, ephemeral=ephemeral)


@app_commands.context_menu(name="Identicon")
async def identicon_context_menu(itx: Interaction, user: discord.Member | discord.User) -> None:
    embed, file = await embed_identicon(user.id, user.name, None, WHITE)
    await itx.response.send_message(embed=embed, file=file, ephemeral=True)


exports = BotExports(commands=[get_identicon, identicon_context_menu])
