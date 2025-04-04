from __future__ import annotations

import logging
import math
import os
import random
from collections.abc import Sequence
from io import BytesIO

import discord
from discord import app_commands
from PIL import Image

from . import _type_shim as t
from ._type import BotExports
from .bot import Interaction
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
    def from_random(cls: type[t.Self]) -> t.Self:
        return cls.from_rgb(random.randint(0, 255), random.randint(0, 255), random.randint(0, 255))

    @classmethod
    def white(cls: type[t.Self]) -> t.Self:
        """A factory method that returns a :class:`Color` with a value of ``0xFFFFFF``.

        .. colour:: #FFFFFF
        """
        return cls(0xFFFFFF)

    @classmethod
    def black(cls: type[t.Self]) -> t.Self:
        """A factory method that returns a :class:`Color` with a value of ``0x000000``.

        .. colour:: #000000
        """
        return cls(0x000000)


WHITE = Color.white()
BLACK = Color.black()


def make_matrix(seed: int, size: int = 6) -> Matrix[int]:
    random.seed(seed)
    width, height = size, size * 2
    result = [([0] * width) for _ in range(height)]
    for i in range(height):
        for j in range(width):
            is_colored = round(random.random(), 2)
            if is_colored <= 0.6:
                result[i][j] = 1

    # flip
    for i in range(height):
        result[i].extend(result[i][::-1])

    return result


def get_colors(seed: int) -> tuple[Color, Color]:
    random.seed(seed)
    primary = Color.from_random()
    secondary = Color.from_random()

    while primary.is_similar_to(secondary):
        primary = Color.from_random()
        secondary = Color.from_random()

    return primary, secondary


def color_matrix(
    matrix: Matrix[int],
    primary: Color = BLACK,
    secondary: Color = WHITE,
) -> Matrix[Color]:
    width, height = len(matrix[0]), len(matrix)
    colored: Matrix[Color] = [[primary] * width for _ in range(height)]
    for i in range(height):
        for j in range(width):
            colored[i][j] = primary if matrix[i][j] == 1 else secondary

    return colored


@executor_function
def make_identicon(matrix: Matrix[Color]) -> bytes:
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


async def embed_identicon(seed: int, title: str) -> tuple[discord.Embed, discord.File]:
    matrix = make_matrix(seed)
    primary, secondary = get_colors(seed)
    colors = color_matrix(matrix, primary, secondary)
    identicon_bytes = await make_identicon(colors)

    file = discord.File(BytesIO(identicon_bytes), filename="identicon.png")
    embed = discord.Embed(title=title, color=primary)
    embed.set_image(url="attachment://identicon.png")
    return embed, file


@app_commands.command(name="identicon", description="Generate an identicon from a seed")
@app_commands.describe(value="Input used to generate icon", ephemeral="Send privately")
async def get_identicon(
    itx: Interaction,
    value: str | None = None,
    ephemeral: bool = False,
) -> None:
    seed_bytes = os.urandom(8) if value is None or not value else value.encode()
    seed = int.from_bytes(seed_bytes, "big")
    title = value or str(seed)

    embed, file = await embed_identicon(seed, title)

    await itx.response.send_message(embed=embed, file=file, ephemeral=ephemeral)


@app_commands.context_menu(name="Identicon")
async def identicon_context_menu(itx: Interaction, user: discord.Member | discord.User) -> None:
    embed, file = await embed_identicon(user.id, user.name)
    await itx.response.send_message(embed=embed, file=file, ephemeral=True)


exports = BotExports(commands=[get_identicon, identicon_context_menu])
