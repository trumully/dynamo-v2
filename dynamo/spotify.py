import datetime
import logging
from collections.abc import Generator
from contextlib import contextmanager
from enum import StrEnum
from functools import partial
from io import BytesIO

import aiohttp
import discord
from async_utils.task_cache import lrutaskcache
from discord import app_commands
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from dynamo.bot import BotExports, Interaction

from . import _typings as t
from .utils.color import Color
from .utils.files import ROOT, resolve_path_with_links
from .utils.format import FONTS, human_join, is_cjk
from .utils.wrappers import executor_function

log = logging.getLogger(__name__)


class Card(t.TypedDict, total=False):
    activity: t.Required[discord.Spotify]
    image: t.Required[Image.Image]
    draw: t.Required[ImageDraw.ImageDraw]


WHITE = Color.white().to_rgb()
GRAY = (64, 64, 64)

LOGO_PATH = resolve_path_with_links(ROOT / "assets" / "img" / "spotify.png")

BLUR = ImageFilter.GaussianBlur(radius=30)
LOGO_SIZE = (48, 48)  # px
SIZE = (800, 250)
ALBUM_SIZE = (250, 250)  # px

OFFSET = 20
PADDING = 15

CONTENT_X = ALBUM_SIZE[0] + OFFSET
CONTENT_MAX_WIDTH = SIZE[0] - CONTENT_X - PADDING - LOGO_SIZE[0]

PROG_BAR_HEIGHT = 6
PROG_BAR_WIDTH = SIZE[0] - CONTENT_X - PADDING - 70
PROG_BAR_X = ALBUM_SIZE[0] + OFFSET
PROG_BAR_Y = SIZE[1] - PROG_BAR_HEIGHT - PADDING - 30
PROG_BAR_LENGTH = PROG_BAR_X + PROG_BAR_WIDTH
PROG_TXT_Y = SIZE[1] - PADDING - 24

FONT_LARGE = 28
FONT_MEDIUM = 22
FONT_SMALL = 18

MAX_SLIDE_SPEED = 10
BASE_SLIDE_SPEED = 2
ANIMATION_TIME = 1_000
MAX_FRAME_DURATION = 100
MIN_FRAME_DURATION = 30
FRAME = ANIMATION_TIME // MIN_FRAME_DURATION


class Format(StrEnum):
    STATIC = "png"
    ANIMATED = "gif"


def url_cache_transform(
    args: tuple[aiohttp.ClientSession, str], kwargs: dict[str, object]
) -> tuple[tuple[str], dict[str, object]]:
    _client, url = args
    return (url.casefold(),), kwargs


@lrutaskcache(maxsize=50, cache_transform=url_cache_transform)
async def get_album_cover(session: aiohttp.ClientSession, url: str, /) -> bytes:
    async with session.get(url) as r:
        r.raise_for_status()
        return await r.read()


def get_font(text: str, size: int, /, *, bold: bool = False) -> ImageFont.FreeTypeFont:
    family = FONTS[is_cjk(text)]
    p = family.bold if bold else family.regular
    return ImageFont.truetype(str(p), size)


async def make_embed(
    mention: str, session: aiohttp.ClientSession, activity: discord.Spotify
) -> tuple[discord.Embed, discord.File]:
    cover = await get_album_cover(session, activity.album_cover_url)
    image, ext = await draw(activity, cover)
    filename = "spotify-card." + ext
    track = f"**[{activity.title}](<{activity.track_url}>)**"
    artists = f"**{human_join(activity.artists)}**"
    description = f"{mention} is listening to {track} by {artists}"
    embed = discord.Embed(
        title="Now Playing", description=description, color=activity.color
    )
    file = discord.File(image, filename)
    embed.set_image(url=f"attachment://{filename}")
    return embed, file


@executor_function
def draw(activity: discord.Spotify, album: bytes) -> tuple[BytesIO, str]:
    title_font = get_font(activity.title, FONT_LARGE, bold=True)
    _, _, title_width, *_ = title_font.getbbox(activity.title)
    with make_card(activity) as card:
        with open_image_bytes(album) as album_cover:
            album_copy = album_cover.copy()
            gradient = make_gradient(album_copy)
            album_copy = album_copy.resize(ALBUM_SIZE)  # type: ignore[reportUnknownMemberType]
            card["image"].paste(gradient, (0, 0))
            card["image"].paste(album_copy, (0, 0))

        # If there is no overflow, make a static image
        if int(title_width) <= CONTENT_MAX_WIDTH:
            card["draw"].text((CONTENT_X, PADDING), activity.title, WHITE, title_font)
            draw_static(**card)
            return save_image(card["image"], Format.STATIC)

        # Make an animated image instead
        text_frames = draw_scroll_text(title_font, activity.title, CONTENT_MAX_WIDTH)
        frames = [make_card_frame(frame, **card) for frame in text_frames]
        frame_duration = min(
            MAX_FRAME_DURATION, max(ANIMATION_TIME // len(frames), MIN_FRAME_DURATION)
        )
        return save_image(
            frames[0],
            Format.ANIMATED,
            save_all=True,
            append_images=frames[1:],
            frame_duration=frame_duration,
            loop=0,
        )


def save_image(im: Image.Image, fmt: Format, /, **kwargs: object) -> tuple[BytesIO, str]:
    buffer = BytesIO()
    im.save(buffer, fmt, **kwargs)
    buffer.seek(0)
    return buffer, fmt


def draw_scroll_text(
    font: ImageFont.FreeTypeFont, text: str, width: int, /
) -> Generator[Image.Image]:
    *_, text_width, text_height = font.getbbox(text)
    size = (width, int(text_height))
    if int(text_width) <= width:
        yield make_scroll_text_frame(text, size, font)
        return

    padded_text = f"{text}   {text}"
    _, _, full_width, *_ = font.getbbox(padded_text)
    slide_speed = min(MAX_SLIDE_SPEED, max(BASE_SLIDE_SPEED, full_width // FRAME))
    num_frames = int(min(FRAME, full_width // slide_speed))

    for i in range(num_frames):
        x_pos = int(-i * slide_speed % full_width)
        yield make_scroll_text_frame(padded_text, size, font, x_pos)


def make_scroll_text_frame(
    text: str, size: tuple[int, int], font: ImageFont.FreeTypeFont, x_pos: int = 0, /
) -> Image.Image:
    frame = Image.new("RGBA", size)
    draw = ImageDraw.Draw(frame)
    x_offset = x_pos + font.getbbox(text)[2]
    draw.text((x_pos, 0), text, WHITE, font)
    draw.text((x_offset, 0), text, WHITE, font)
    return frame


def make_card_frame(frame: Image.Image, **card: t.Unpack[Card]) -> Image.Image:
    card_copy = card.copy()
    card_frame = card_copy["image"].copy()
    card_frame.paste(frame, (CONTENT_X, PADDING), frame)

    card_copy["draw"] = ImageDraw.Draw(card_frame)

    draw_static(**card_copy)
    return card_frame


def format_seconds(seconds: int, /) -> str:
    mins, secs = divmod(seconds, 60)
    hrs, mins = divmod(mins, 60)
    result: list[str] = [f"{mins:02d}", f"{secs:02d}"]
    if hrs > 0:
        result.insert(0, str(hrs))
    return ":".join(result)


def _song_progress(end: datetime.datetime, duration: datetime.timedelta, /) -> float:
    """Get song progress as a percentage."""
    remaining = end - discord.utils.utcnow()
    return 1 - (remaining.total_seconds() / duration.total_seconds())


@contextmanager
def open_image_bytes(image: bytes, /) -> Generator[Image.Image]:
    buffer = BytesIO(image)
    buffer.seek(0)
    with Image.open(buffer) as im:
        try:
            yield im
        finally:
            buffer.close()


@contextmanager
def make_card(activity: discord.Spotify) -> Generator[Card]:
    with Image.new("RGBA", SIZE) as im:
        yield {"image": im, "draw": ImageDraw.Draw(im), "activity": activity}


def draw_static(**card: t.Unpack[Card]) -> None:
    image = card["image"]
    draw = card["draw"]
    activity = card["activity"]

    artists = ", ".join(activity.artists)
    draw.text(
        (CONTENT_X, PADDING + FONT_LARGE + 5),
        artists,
        WHITE,
        get_font(artists, FONT_MEDIUM),
    )

    draw_progress_bar(draw, activity.end, activity.duration)

    with Image.open(LOGO_PATH) as logo_base:
        logo = logo_base.resize(LOGO_SIZE)  # type: ignore[reportUnknownMemberType]
        xy = (SIZE[0] - LOGO_SIZE[0] - PADDING, PADDING)
        image.paste(logo, xy, logo)


def _prog_bar_length_relative_to(relative_width: int) -> tuple[int, int, int, int]:
    return (PROG_BAR_X, PROG_BAR_Y, relative_width, PROG_BAR_Y + PROG_BAR_HEIGHT)


def draw_progress_bar(
    draw: ImageDraw.ImageDraw,
    end: datetime.datetime,
    duration: datetime.timedelta,
    /,
) -> None:
    progress = _song_progress(end, duration)
    prog_width = max(
        PROG_BAR_X,
        min(PROG_BAR_LENGTH, (PROG_BAR_X + int(PROG_BAR_WIDTH * progress))),
    )

    # Full duration bar
    draw.rectangle(_prog_bar_length_relative_to(PROG_BAR_LENGTH), GRAY)

    # Draw progress if there is any on the track
    if prog_width > PROG_BAR_X:
        draw.rectangle(_prog_bar_length_relative_to(prog_width), WHITE)

    duration_seconds = int(duration.total_seconds())
    played = int(min(duration_seconds, duration_seconds * progress))
    prog_txt = f"{format_seconds(played)} / {format_seconds(duration_seconds)}"
    draw.text((PROG_BAR_X, PROG_TXT_Y), prog_txt, WHITE, get_font(prog_txt, FONT_SMALL))


def make_gradient(cover_copy: Image.Image, /) -> Image.Image:
    blurred = cover_copy.resize(SIZE).filter(BLUR)  # type: ignore[reportUnknownMemberType]

    with Image.new("RGBA", SIZE) as g:
        draw = ImageDraw.Draw(g)
        for y in range(SIZE[1]):
            pos = ((0, y), (SIZE[0], y))
            alpha = int(255 * (1 - y / SIZE[1]))
            draw.line(pos, (0, 0, 0, alpha))

        blurred = Image.alpha_composite(blurred.convert("RGBA"), g)
        darkened = Image.new("RGBA", blurred.size, (0, 0, 0, 64))
        result = Image.alpha_composite(blurred, darkened)

        blurred.close()
        darkened.close()

        return result


@app_commands.command(name="spotify", description="Get Spotify info in a stylish embed")
@app_commands.guild_only()
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
    member = itx.guild.get_member(user.id)

    if member is None:
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
