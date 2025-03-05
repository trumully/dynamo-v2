from __future__ import annotations

import os
import random
from io import BytesIO
from typing import TYPE_CHECKING, Any

import discord
from discord import AppCommandOptionType, app_commands
from discord.app_commands import Transform
from PIL import Image

from dynamo._type import BotExports
from dynamo.utils.wrappers import executor_function

if TYPE_CHECKING:
    from dynamo.bot import Interaction


IDENTICON_SIZE = 500

type UserOrString = discord.User | discord.Member | str
type Color = tuple[int, int, int]
type Matrix[T] = list[list[T]]

WHITE: Color = (255, 255, 255)
BLACK: Color = (0, 0, 0)


class UserOrStringTransformer(app_commands.Transformer["Dynamo"]):  # type: ignore[reportUndefinedVariable]
    async def transform(self, interaction: Interaction, value: Any, /) -> UserOrString:
        if not isinstance(value, discord.Member | discord.User | str):
            raise app_commands.TransformerError(value, self.type, self)
        return value

    @property
    def type(self) -> AppCommandOptionType:
        return AppCommandOptionType.string


def seed_from_user_or_string(user_or_string: UserOrString) -> int:
    if isinstance(user_or_string, discord.Member | discord.User):
        return user_or_string.id

    if user_or_string.isdigit():
        return int(user_or_string)
    return int.from_bytes(user_or_string.encode(), "big", signed=True)


def title_from_user_or_string(user_or_string: UserOrString) -> str:
    if isinstance(user_or_string, discord.User | discord.Member):
        return user_or_string.name

    return str(user_or_string)


def make_matrix(seed: int, size: int = 6) -> Matrix[int]:
    random.seed(seed)
    width, height = size, size * 2
    result = [([0] * width) for _ in range(height)]
    for i in range(height):
        for j in range(width):
            is_colored = round(random.random(), 2)
            if is_colored > 0.6:
                result[i][j] = 1

    # flip
    for i in range(height):
        result[i].extend(result[i][::-1])

    return result


def get_colors(seed: int) -> tuple[Color, Color]:
    primary: Color
    secondary: Color

    random.seed(seed)
    primary = (random.randint(0, 255), random.randint(0, 255), random.randint(0, 255))
    secondary = (random.randint(0, 255), random.randint(0, 255), random.randint(0, 255))

    return primary, secondary


def color_matrix_in_place(
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
def make_identicon(matrix: Matrix[int]) -> bytes:
    buffer = BytesIO()

    matrix_width, matrix_height = len(matrix[0]), len(matrix)

    image = Image.new("RGB", (matrix_width, matrix_height), 255)
    data = image.load()  # type: ignore[reportUnknownMemberType]
    assert data is not None
    for i in range(matrix_height):
        for j in range(matrix_width):
            data[i, j] = matrix[i][j]

    image = image.resize((IDENTICON_SIZE, IDENTICON_SIZE), Image.Resampling.NEAREST)  # type: ignore[reportUnknownMemberType]
    image = image.rotate(90, Image.Resampling.NEAREST)
    image.save(buffer, format="png")

    buffer.seek(0)
    return buffer.getvalue()


async def embed_identicon(seed: int, title: str) -> tuple[discord.Embed, discord.File]:
    matrix = make_matrix(seed)
    primary, secondary = get_colors(seed)
    color_matrix_in_place(matrix, primary, secondary)
    identicon_bytes = await make_identicon(matrix)

    file = discord.File(BytesIO(identicon_bytes), filename="identicon.png")
    embed = discord.Embed(title=title)
    embed.set_image(url="attachment://identicon.png")
    return embed, file


@app_commands.command(name="identicon", description="Generate an identicon from a seed")
@app_commands.describe(
    seed="Seed used to generate icon", ephemeral="Result is sent privately"
)
async def get_identicon(
    itx: Interaction,
    seed: Transform[UserOrString, UserOrStringTransformer] | None = None,
    ephemeral: bool = False,
) -> None:
    seed_: int
    if seed is None:
        seed_ = int.from_bytes(os.urandom(8), "big", signed=True)
    else:
        seed_ = seed_from_user_or_string(seed)

    title = title_from_user_or_string(seed if seed is not None else str(seed_))
    embed, file = await embed_identicon(seed_, title)

    await itx.response.send_message(embed=embed, file=file, ephemeral=True)


@app_commands.context_menu(name="Identicon")
async def identicon_context_menu(
    itx: Interaction, user: discord.Member | discord.User
) -> None:
    seed = seed_from_user_or_string(user)
    embed, file = await embed_identicon(seed, str(user))
    await itx.response.send_message(embed=embed, file=file, ephemeral=True)


exports = BotExports(commands=[get_identicon, identicon_context_menu])
