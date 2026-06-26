from __future__ import annotations

from functools import partial
from io import BytesIO

import aiohttp
import discord
from async_utils.task_cache import lrutaskcache
from discord import app_commands
from imagetext_py import Color as FontColor
from imagetext_py import FontDB, Paint, Writer
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from . import _typings as t
from ._types import BotExports
from .bot import Interaction
from .color import Color
from .logs import Logger, get_logger
from .utils import ROOT, afunc, human_join

log: Logger = get_logger(__name__)

FONT_LARGE = 42
FONT_MEDIUM = 28
FONT_SMALL = 24

FONT_PATH = ROOT / "assets" / "fonts"

FontDB.LoadFromDir(str(FONT_PATH))
FONT = FontDB.Query(" ".join(font.stem for font in FONT_PATH.rglob("*.ttf")))
# Font size differs between imagetext_py and PIL. I still want to use PIL for truncation
# But use imagetext_py for (easy) fallback fonts
MEDIUM = ImageFont.FreeTypeFont(FONT_PATH / "NotoSans-Regular.ttf", FONT_MEDIUM - 6)
LARGE = ImageFont.FreeTypeFont(FONT_PATH / "NotoSans-Regular.ttf", FONT_LARGE - 10)

WHITE = Color.white().to_rgb()
PAINT_WHITE = Paint(FontColor(*WHITE, 255))
GRAY = (80, 80, 80)

BLUR = ImageFilter.GaussianBlur(radius=30)
LOGO_SIZE = LOGO_WIDTH, LOGO_HEIGHT = (48, 48)
SIZE = WIDTH, HEIGHT = (800, 250)
ALBUM_SIZE = ALBUM_WIDTH, ALBUM_HEIGHT = (250, 250)

PADDING = 15

CONTENT_X = ALBUM_WIDTH + 20
CONTENT_MAX_WIDTH = WIDTH - CONTENT_X - PADDING - LOGO_WIDTH

BAR_HEIGHT = 6
BAR_WIDTH = WIDTH - CONTENT_X - PADDING - 70
BAR_X = ALBUM_WIDTH + 20
BAR_Y = HEIGHT - BAR_HEIGHT - PADDING - 30
BAR_LENGTH = BAR_X + BAR_WIDTH
BAR_TEXT_Y = HEIGHT - PADDING - 24

LOGO_URL = "https://storage.googleapis.com/pr-newsroom-wp/1/2023/05/Spotify_Primary_Logo_RGB_White.png"


def url_cache_transform(
    args: tuple[aiohttp.ClientSession, str], kwargs: t.Mapping[str, object]
) -> tuple[tuple[str], t.Mapping[str, object]]:
    _client, url = args
    return (url.casefold(),), kwargs


@lrutaskcache(maxsize=50, cache_transform=url_cache_transform)
async def get_image(session: aiohttp.ClientSession, url: str, /) -> BytesIO:
    async with session.get(url) as r:
        if r.status != 200:
            r.raise_for_status()
        buff = BytesIO(await r.read())
        buff.seek(0)
        return buff


async def try_get_image(session: aiohttp.ClientSession, url: str, /) -> BytesIO:
    try:
        return await get_image(session, url)
    except aiohttp.ClientError:
        log.exception("Failed to get image at %s", url)
        raise


async def send_spotify_embed(itx: Interaction, mention: str, activity: discord.Spotify) -> None:
    cover = await try_get_image(itx.client.session, activity.album_cover_url)
    logo = await try_get_image(itx.client.session, LOGO_URL)
    image = await draw(cover, logo, activity)
    track = f"**[{activity.title}](<{activity.track_url}>)**"
    artists = f"**{human_join(activity.artists)}**"
    description = f"{mention} is listening to {track} by {artists}"
    embed = discord.Embed(
        title="<:_:1286859010045247488> Now Playing",
        description=description,
        color=activity.color,
    )
    file = discord.File(image, "spotify.png")
    embed.set_image(url="attachment://spotify.png")
    await itx.response.send_message(embed=embed, file=file)


def truncate(text: str, font: ImageFont.FreeTypeFont, max_length: int = CONTENT_MAX_WIDTH) -> str:
    result = ""
    for c in text:
        result += c
        if font.getlength(result) > max_length:
            return result[:-2] + "..."
    return result


def time_from_seconds(seconds: int) -> str:
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    result = [f"{seconds:02d}", f"{minutes:02d}"]
    if hours > 0:
        result.append(f"{hours:02d}")
    return ":".join(result[::-1])


@afunc()
def draw(album_buff: BytesIO, logo_buff: BytesIO, activity: discord.Spotify) -> BytesIO:
    # unknown type because resize() uses numpy types under the hood
    cover = Image.open(album_buff).convert("RGBA").resize(ALBUM_SIZE)  # pyright: ignore[reportUnknownMemberType]

    seconds = activity.duration.total_seconds()
    progress = 1 - ((activity.end - discord.utils.utcnow()).total_seconds() / seconds)

    time_on = time_from_seconds(int(seconds * progress))
    time_end = time_from_seconds(int(seconds))

    with make_gradient(cover) as img:
        draw = ImageDraw.Draw(img)
        img.paste(cover, (0, 0), cover)

        # unknown type because resize() uses numpy types under the hood
        with Image.open(logo_buff).resize(LOGO_SIZE) as logo:  # pyright: ignore[reportUnknownMemberType]
            img.paste(logo, (WIDTH - LOGO_WIDTH - PADDING, PADDING), logo)

        with Writer(img) as w:
            draw_text = partial(w.draw_text, font=FONT, fill=PAINT_WHITE)

            title = truncate(activity.title, LARGE)
            draw_text(title, CONTENT_X, PADDING, FONT_LARGE)

            artists = truncate(", ".join(activity.artists), MEDIUM)
            draw_text(artists, CONTENT_X, PADDING + FONT_LARGE + 5, FONT_MEDIUM)

            # Singles have the title as the album, don't draw it if that is the case
            if activity.title != activity.album:
                album = truncate(activity.album, MEDIUM)
                draw_text(album, CONTENT_X, PADDING + FONT_LARGE + FONT_MEDIUM + 10, FONT_MEDIUM)

            draw_text(f"{time_on} / {time_end}", BAR_X, BAR_TEXT_Y, FONT_SMALL)

        draw.rectangle((BAR_X, BAR_Y, BAR_LENGTH, BAR_Y + BAR_HEIGHT), GRAY)

        played = BAR_X + (progress * BAR_WIDTH)
        draw.rectangle((BAR_X, BAR_Y, int(played), BAR_Y + BAR_HEIGHT), WHITE)

    buf = BytesIO()
    img.save(buf, "PNG")
    buf.seek(0)

    return buf


def make_gradient(cover: Image.Image, /) -> Image.Image:
    with Image.new("RGBA", SIZE) as g:
        draw = ImageDraw.Draw(g)
        for y in range(HEIGHT):
            pos = ((0, y), (WIDTH, y))
            alpha = int(255 * (1 - y / HEIGHT))
            draw.line(pos, (0, 0, 0, alpha))

    # unknown type because resize() uses numpy types under the hood
    with cover.convert("RGBA").resize(SIZE).filter(BLUR) as blurred:  # pyright: ignore[reportUnknownMemberType]
        gradient_applied = Image.alpha_composite(blurred, g)

    with Image.new("RGBA", SIZE, (0, 0, 0, 64)) as darkened:
        return Image.alpha_composite(gradient_applied, darkened)


@app_commands.command(name="spotify", description="Get Spotify info in a stylish embed")
@app_commands.describe(user="The user to check. You by default")
@app_commands.checks.cooldown(1, 5.0, key=lambda i: i.user.id)
@app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
async def get_spotify(itx: Interaction, user: (discord.Member | discord.User) | None = None) -> None:
    assert itx.guild is not None, "This is a guild only command"

    user = itx.user if user is None else user

    if (member := itx.guild.get_member(user.id)) is None:
        await itx.response.send_message("That member is not in this guild.", ephemeral=True)
        return

    activity = next((a for a in member.activities if isinstance(a, discord.Spotify)), None)
    if activity is None:
        prefix = "You are" if user.id == itx.user.id else f"{user!s} is"
        await itx.response.send_message(f"{prefix} not listening to Spotify", ephemeral=True)
        return

    try:
        await send_spotify_embed(itx, user.mention, activity)
    except Exception as ex:
        msg = "Something went wrong, please try again."
        log.exception(msg, exc_info=ex)
        await itx.response.send_message(msg, ephemeral=True)


exports: BotExports = BotExports(commands=[get_spotify])
