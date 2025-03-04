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
    from .bot import Interaction


IDENTICON_SIZE = 500

type UserOrString = discord.User | discord.Member | str
type Color = tuple[int, int, int]
type Matrix[T] = list[list[T]]

WHITE: Color = (255, 255, 255)
BLACK: Color = (0, 0, 0)


class UserOrStringTransformer(app_commands.Transformer["Dynamo"]):
    async def transform(self, interaction: Interaction, value: Any, /) -> UserOrString:
        if not isinstance(value, discord.Member | discord.User | str):
            raise app_commands.TransformerError(value, self.type, self)
        return value

    @property
    def type(self) -> AppCommandOptionType:
        return AppCommandOptionType.string


def seed_from_user_or_string(user_or_string: UserOrString) -> int:
    if isinstance(user_or_string, discord.User | discord.Member):
        return user_or_string.id

    if str(user_or_string).isdigit():
        return int(user_or_string)

    return user_or_string


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
    matrix_out: Matrix[int],
    primary: Color = BLACK,
    secondary: Color = WHITE,
) -> Matrix[Color]:
    width, height = len(matrix_out[0]), len(matrix_out)
    for i in range(height):
        for j in range(width):
            matrix_out[i][j] = primary if matrix_out[i][j] == 1 else secondary


@executor_function
def make_identicon(matrix: Matrix[int]) -> bytes:
    buffer = BytesIO()

    matrix_width, matrix_height = len(matrix[0]), len(matrix)

    image = Image.new("RGB", (matrix_width, matrix_height), 255)
    data = image.load()
    for i in range(matrix_height):
        for j in range(matrix_width):
            data[i, j] = matrix[i][j]

    image = image.resize((IDENTICON_SIZE, IDENTICON_SIZE), Image.Resampling.NEAREST)
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
@app_commands.describe(seed="Seed used to generate icon", ephemeral="Result is sent privately")
async def get_identicon(
    itx: Interaction,
    seed: Transform[UserOrString, UserOrStringTransformer] | None = None,
    ephemeral: bool = False,
) -> None:
    seed_ = seed_from_user_or_string(seed) or int.from_bytes(os.urandom(8), "big", signed=True)
    embed, file = await embed_identicon(seed_, title_from_user_or_string(seed or seed_))

    await itx.response.send_message(embed=embed, file=file, ephemeral=True)


@app_commands.context_menu(name="Identicon")
async def identicon_context_menu(itx: Interaction, user: discord.Member | discord.User) -> None:
    seed = seed_from_user_or_string(user)
    embed, file = await embed_identicon(seed, str(user))
    await itx.response.send_message(embed=embed, file=file, ephemeral=True)


exports = BotExports(commands=[get_identicon, identicon_context_menu])
