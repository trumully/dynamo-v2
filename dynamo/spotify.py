import datetime
import logging
from collections.abc import Sequence
from functools import partial
from io import BytesIO

import aiohttp
import discord
from async_utils.task_cache import lrutaskcache
from discord import app_commands
from imagetext_py import Color as TextColor
from imagetext_py import FontDB, Paint, Writer
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from . import _typing_shim as t
from ._typings import BotExports
from .bot import Interaction
from .utils.color import Color
from .utils.files import ROOT
from .utils.format import human_join
from .utils.wrappers import run_in_thread

log = logging.getLogger(__name__)

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
PAINT_WHITE = Paint(t.cast(TextColor, (*WHITE, 255)))
GRAY = (80, 80, 80)

BLUR = ImageFilter.GaussianBlur(radius=30)
LOGO_SIZE = LOGO_WIDTH, LOGO_HEIGHT = (48, 48)  # px
SIZE = WIDTH, HEIGHT = (800, 250)
ALBUM_SIZE = ALBUM_WIDTH, ALBUM_HEIGHT = (250, 250)  # px

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
    args: tuple[aiohttp.ClientSession, str], kwargs: dict[str, object]
) -> tuple[tuple[str], dict[str, object]]:
    _client, url = args
    return (url.casefold(),), kwargs


@lrutaskcache(maxsize=50, cache_transform=url_cache_transform)
async def get_image(session: aiohttp.ClientSession, url: str, /) -> bytes:
    async with session.get(url) as r:
        r.raise_for_status()
        return await r.read()


async def make_embed(
    mention: str, session: aiohttp.ClientSession, activity: discord.Spotify
) -> tuple[discord.Embed, discord.File]:
    cover = await get_image(session, activity.album_cover_url)
    logo = await get_image(session, LOGO_URL)
    image = await draw(
        activity.title,
        activity.artists,
        activity.album,
        cover,
        logo,
        activity.duration,
        activity.end,
    )
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
    return embed, file


def truncate(
    text: str, font: ImageFont.FreeTypeFont, max_length: int = CONTENT_MAX_WIDTH
) -> str:
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


@run_in_thread
def draw(
    track_name: str,
    artists: Sequence[str],
    album_name: str,
    album_cover: bytes,
    logo_bytes: bytes,
    duration: datetime.timedelta,
    end: datetime.datetime,
) -> BytesIO:
    cover_buf = BytesIO(album_cover)
    cover_buf.seek(0)
    # unknown type because resize() uses numpy types under the hood
    cover = Image.open(cover_buf).convert("RGBA").resize(ALBUM_SIZE)  # type: ignore[reportUnknownMemberType]

    duration_seconds = duration.total_seconds()
    progress = 1 - ((end - discord.utils.utcnow()).total_seconds() / duration_seconds)

    time_on = time_from_seconds(int(duration_seconds * progress))
    time_end = time_from_seconds(int(duration_seconds))

    with make_gradient(cover) as img:
        draw = ImageDraw.Draw(img)
        img.paste(cover, (0, 0), cover)

        logo_buf = BytesIO(logo_bytes)
        logo_buf.seek(0)
        # unknown type because resize() uses numpy types under the hood
        with Image.open(logo_buf).resize(LOGO_SIZE) as logo:  # type: ignore[reportUnknownMemberType]
            img.paste(logo, (WIDTH - LOGO_WIDTH - PADDING, PADDING), logo)

        with Writer(img) as w:
            draw_text = partial(w.draw_text, font=FONT, fill=PAINT_WHITE)

            draw_text(
                truncate(track_name, LARGE),
                CONTENT_X,
                PADDING,
                FONT_LARGE,
            )

            draw_text(
                truncate(", ".join(artists), MEDIUM),
                CONTENT_X,
                PADDING + FONT_LARGE + 5,
                FONT_MEDIUM,
            )

            # Singles have the title as the album, don't draw it if that is the case
            if track_name != album_name:
                draw_text(
                    truncate(album_name, MEDIUM),
                    CONTENT_X,
                    PADDING + FONT_LARGE + FONT_MEDIUM + 10,
                    FONT_MEDIUM,
                )

            draw_text(
                f"{time_on} / {time_end}",
                BAR_X,
                BAR_TEXT_Y,
                FONT_SMALL,
            )

        draw.rectangle(
            (BAR_X, BAR_Y, BAR_LENGTH, BAR_Y + BAR_HEIGHT),
            GRAY,
        )

        played = BAR_X + (progress * BAR_WIDTH)
        draw.rectangle(
            (BAR_X, BAR_Y, int(played), BAR_Y + BAR_HEIGHT),
            WHITE,
        )

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
    with cover.convert("RGBA").resize(SIZE).filter(BLUR) as blurred:  # type: ignore[reportUnknownMemberType]
        gradient_applied = Image.alpha_composite(blurred, g)

    with Image.new("RGBA", SIZE, (0, 0, 0, 64)) as darkened:
        return Image.alpha_composite(gradient_applied, darkened)


@app_commands.command(name="spotify", description="Get Spotify info in a stylish embed")
@app_commands.guild_only()
@app_commands.checks.cooldown(1, 5.0, key=lambda i: i.user.id)
@app_commands.describe(user="The user to check. You by default")
async def get_spotify(
    itx: Interaction, user: (discord.Member | discord.User) | None = None
) -> None:
    send = itx.response.send_message
    error = partial(send, ephemeral=True)

    if itx.guild is None:
        await error("Please use this command in a guild.")
        return

    user = itx.user if user is None else user

    if (member := itx.guild.get_member(user.id)) is None:
        await error("That member is not in this guild.")
        return

    activity: discord.Spotify
    try:
        activity = next(a for a in member.activities if isinstance(a, discord.Spotify))
    except StopIteration:
        prefix = "You are" if user.id == itx.user.id else f"{user!s} is"
        await error(f"{prefix} not listening to Spotify")
        return

    try:
        embed, file = await make_embed(user.mention, itx.client.session, activity)
        await send(embed=embed, file=file)
    except aiohttp.ClientError:
        log.warning(
            "Failed to fetch Spotify album cover for %s",
            activity.album_cover_url,
            exc_info=True,
        )
        await error("Sorry, I couldn't fetch the album cover. Please try again.")
    except Exception:
        log.exception(
            "Failed to generate Spotify card for user %s (%s)", user.display_name, user.id
        )
        await error("Sorry, something went wrong while creating the Spotify card image.")


exports = BotExports(commands=[get_spotify])
