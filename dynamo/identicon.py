from __future__ import annotations

import logging
import os
import random
from collections.abc import Sequence
from io import BytesIO
from typing import TYPE_CHECKING, NamedTuple, Self

import discord
from discord import app_commands
from PIL import Image

from dynamo._type import BotExports
from dynamo.utils.wrappers import executor_function

if TYPE_CHECKING:
    from dynamo.bot import Interaction


IDENTICON_SIZE = 500

type Matrix[T] = Sequence[Sequence[T]]


MAX_PERCEIVED = 764.83
MAX_EUCLEDIAN = 441.67

# lower value = more similar
SIMILARITY_CUTOFF = 0.3

EPSILON = 1e-6

log = logging.getLogger(__name__)


class RGB(NamedTuple):
    r: int
    g: int
    b: int

    def __sub__(self, other: object) -> tuple[int, int, int]:
        if isinstance(other, RGB):
            return self.r - other.r, self.g - other.g, self.b - other.b
        return NotImplemented

    @staticmethod
    def colors_similar(x: RGB, y: RGB) -> bool:
        p_dist = x.perceived_distance_from(y)
        e_dist = x.euclidean_distance_from(y)

        thresh = SIMILARITY_CUTOFF * (1 + abs((sum(x) / 765) - (sum(y) / 765)))

        return p_dist <= (thresh + EPSILON) and e_dist <= (thresh + EPSILON)

    def perceived_distance_from(self, other: RGB) -> float:
        """Uses cmetric formula from `CompuPhase`_:

        `ΔC = √((2 + r̄/256) * ΔR² + 4 * ΔG² + (2 + (255 - r̄)/256) * ΔB²)`

        .. _CompuPhase:
            https://www.compuphase.com/cmetric.htm
        """
        r_mean = (self.r + other.r) >> 1
        # delta of r, g, b each is squared
        r, g, b = (x**2 for x in (self - other))
        distance = (((512 * r_mean) * r) >> 8) + 4 * g + (((767 - r_mean) * b) >> 8) ** 0.5
        return distance / MAX_PERCEIVED

    def euclidean_distance_from(self, other: RGB) -> float:
        return (sum(x**2 for x in (self - other)) ** 0.5) / MAX_EUCLEDIAN

    @classmethod
    def from_hex(cls: type[Self], h: str) -> Self:
        return cls(*(int(h.lstrip("#")[i : i + 2], 16) for i in (0, 2, 4)))


WHITE = RGB(255, 255, 255)
BLACK = RGB(0, 0, 0)


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


def get_colors(seed: int) -> tuple[RGB, RGB]:
    random.seed(seed)
    primary = RGB(random.randint(0, 255), random.randint(0, 255), random.randint(0, 255))
    secondary = RGB(random.randint(0, 255), random.randint(0, 255), random.randint(0, 255))

    while RGB.colors_similar(primary, secondary):
        primary = RGB(random.randint(0, 255), random.randint(0, 255), random.randint(0, 255))
        secondary = RGB(random.randint(0, 255), random.randint(0, 255), random.randint(0, 255))

    return primary, secondary


def color_matrix(
    matrix: Matrix[int],
    primary: RGB = BLACK,
    secondary: RGB = WHITE,
) -> Matrix[RGB]:
    width, height = len(matrix[0]), len(matrix)
    colored: Matrix[RGB] = [[primary] * width for _ in range(height)]
    for i in range(height):
        for j in range(width):
            colored[i][j] = primary if matrix[i][j] == 1 else secondary

    return colored


@executor_function
def make_identicon(matrix: Matrix[RGB]) -> bytes:
    buffer = BytesIO()

    matrix_width, matrix_height = len(matrix[0]), len(matrix)

    image = Image.new("RGB", (matrix_width, matrix_height), 255)
    data = image.load()  # type: ignore[reportUnknownMemberType]
    assert data is not None
    for i in range(matrix_height):
        for j in range(matrix_width):
            r, g, b = matrix[i][j]
            data[i, j] = (r, g, b)

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
    embed = discord.Embed(title=title)
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
    seed = int.from_bytes(seed_bytes, "big", signed=True)
    title = value or str(seed)

    embed, file = await embed_identicon(seed, title)

    await itx.response.send_message(embed=embed, file=file, ephemeral=ephemeral)


@app_commands.context_menu(name="Identicon")
async def identicon_context_menu(itx: Interaction, user: discord.Member | discord.User) -> None:
    embed, file = await embed_identicon(user.id, user.name)
    await itx.response.send_message(embed=embed, file=file, ephemeral=True)


exports = BotExports(commands=[get_identicon, identicon_context_menu])
