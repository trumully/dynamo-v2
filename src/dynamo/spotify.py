from __future__ import annotations

import math
import operator
from io import BytesIO

import aiohttp
import discord
from async_utils.task_cache import lrutaskcache
from discord import app_commands
from imagetext_py import Color as FontColor
from imagetext_py import FontDB, Paint, Writer
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageStat

from . import _typings as t
from ._types import BotExports
from .bot import Interaction
from .logs import Logger, get_logger
from .utils import ROOT, afunc, human_join

log: Logger = get_logger(__name__)

FONT_PATH = ROOT / "assets" / "fonts"

LARGE = 42
MEDIUM = 28
SMALL = 24

FontDB.LoadFromDir(str(FONT_PATH))
FONT = FontDB.Query(" ".join(font.stem for font in FONT_PATH.rglob("*.ttf")))
# Font size differs between imagetext_py and PIL. I still want to use PIL for truncation
# But use imagetext_py for (easy) fallback fonts
MEDIUM_FONT = ImageFont.FreeTypeFont(FONT_PATH / "NotoSans-Regular.ttf", MEDIUM - 6)
LARGE_FONT = ImageFont.FreeTypeFont(FONT_PATH / "NotoSans-Regular.ttf", LARGE - 10)

TEXT_COLOR = Paint(FontColor(255, 255, 255))
STROKE_COLOR = Paint(FontColor(0, 0, 0, 180))

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


class Theme(t.NamedTuple):
    bg: tuple[int, int, int]
    accent: tuple[int, int, int]
    accent_alt: tuple[int, int, int]
    dominant: tuple[int, int, int]
    brightness: float
    is_dark: bool


with Image.open(ROOT / "assets" / "img" / "spotify.png") as logo:
    SPOTIFY_LOGO = logo.convert("RGBA").resize(LOGO_SIZE)  # pyright: ignore[reportUnknownMemberType]


def make_gradient_overlay(size: tuple[int, int], theme: Theme, /) -> Image.Image:
    cx, cy = size[0] * 0.5, size[1] * 0.45  # slightly above center (important)
    max_dist = math.hypot(*size)
    overlay = Image.new("RGBA", size, (0, 0, 0, 0))
    px = overlay.load()
    assert px is not None

    strength = int(200 * (1.0 - theme.brightness))
    strength = max(60, min(220, strength))

    for y in range(size[1]):
        for x in range(size[0]):
            dx = x - cx
            dy = y - cy

            # radial distance
            dist = math.hypot(dx, dy)
            radial = dist / max_dist
            radial *= radial  # smooth falloff

            # vertical bias (darker at bottom)
            vertical = y / size[1]
            vertical **= 1.4

            # slight left emphasis (your text is left-heavy)
            horizontal = 1.0 - (x / size[0])
            horizontal **= 2

            # combine layers (weighted like UI designers do)
            t = radial * 0.45 + vertical * 0.45 + horizontal * 0.10

            top_fade = 1.0 if y > size[1] * 0.15 else (y / (size[1] * 0.15))
            t *= top_fade

            alpha = int(strength * t)

            px[x, y] = (
                int(theme.accent[0] * (1 - t) + theme.accent_alt[0] * t),
                int(theme.accent[1] * (1 - t) + theme.accent_alt[1] * t),
                int(theme.accent[2] * (1 - t) + theme.accent_alt[2] * t),
                int(alpha),
            )

    return overlay


def get_dominant_color(img: Image.Image) -> tuple[int, int, int]:
    img = img.convert("RGB").resize((40, 40))  # pyright: ignore[reportUnknownMemberType]

    colors = img.getcolors(maxcolors=40 * 40)
    assert colors is not None
    _, color_data = max(colors, key=operator.itemgetter(0))
    if not isinstance(color_data, tuple):
        msg = "Expected a tuple"
        raise TypeError(msg)

    return color_data  # pyright: ignore[reportReturnType]  it's an RGB image, not an RGBA image


def extract_palette(img: Image.Image) -> list[tuple[int, int, int]]:
    img = img.convert("RGB").resize((120, 120))  # pyright: ignore[reportUnknownMemberType]
    q = img.quantize(colors=6).convert("RGB")

    counts: dict[tuple[int, int, int], int] = {}
    for c in q.getdata():
        counts[c] = counts.get(c, 0) + 1  # pyright: ignore[reportCallIssue, reportArgumentType]

    sorted_colors = sorted(counts.items(), key=operator.itemgetter(1), reverse=True)
    return [c for c, _ in sorted_colors]


def get_brightness(img: Image.Image) -> float:
    img = img.convert("L").resize((40, 40))  # pyright: ignore[reportUnknownMemberType]
    stat = ImageStat.Stat(img)
    return stat.mean[0]


def saturation(c: tuple[int, int, int]) -> float:
    return max(c) - min(c)


def luminance(c: tuple[int, int, int]) -> float:
    r, g, b = c
    return 0.299 * r + 0.587 * g + 0.114 * b


def region_luminance(img: Image.Image, box: tuple[int, int, int, int]) -> float:
    region = img.crop(box).convert("L")
    return ImageStat.Stat(region).mean[0]


def shadow_alpha(bg_lum: float) -> int:
    return int(220 * (bg_lum / 255))


def build_theme(img: Image.Image, /) -> Theme:
    palette = extract_palette(img)
    brightness = get_brightness(img)
    accent = max(palette, key=saturation)

    return Theme(
        palette[0],
        accent,
        min(palette, key=luminance),
        get_dominant_color(img),
        brightness,
        brightness < 0.5,
    )


DARK_OVERLAY = Image.new("RGBA", SIZE, (0, 0, 0, 64))


def url_cache_transform(
    args: tuple[aiohttp.ClientSession, str], kwargs: t.Mapping[str, object]
) -> tuple[tuple[str], t.Mapping[str, object]]:
    _client, url = args
    return (url.casefold(),), kwargs


def spotify_cache_transform(
    args: tuple[bytes, discord.Spotify], kwargs: t.Mapping[str, object]
) -> tuple[tuple[str, tuple[str, ...], str, int], t.Mapping[str, object]]:
    _image, activity = args
    return (
        (
            activity.title,
            tuple(activity.artists),
            activity.album,
            int(activity.duration.total_seconds()),
        ),
        kwargs,
    )


def truncate(text: str, font: ImageFont.FreeTypeFont, /) -> str:
    if font.getlength(text) <= CONTENT_MAX_WIDTH:
        return text

    low = 0
    high = len(text)

    while low < high:
        mid = (low + high + 1) // 2
        if font.getlength(text[:mid] + "...") <= CONTENT_MAX_WIDTH:
            low = mid
        else:
            high = mid - 1

    return text[:low] + "..."


def time_from_seconds(seconds: int) -> str:
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours > 0:
        return f"{hours}:{minutes:02}:{seconds:02}"
    return f"{minutes}:{seconds:02}"


@lrutaskcache(maxsize=50, cache_transform=url_cache_transform)
async def get_image_bytes(session: aiohttp.ClientSession, url: str, /) -> bytes:
    async with session.get(url) as r:
        r.raise_for_status()
        return await r.read()


@lrutaskcache(maxsize=50, cache_transform=spotify_cache_transform)
@afunc()
def render_static(image_bytes: bytes, activity: discord.Spotify, /) -> tuple[Image.Image, Theme]:
    with Image.open(BytesIO(image_bytes)) as img:
        cover = img.convert("RGBA").resize(ALBUM_SIZE)  # pyright: ignore[reportUnknownMemberType]
        full = img.convert("RGB")

    theme = build_theme(full)

    with cover.convert("RGBA").resize(SIZE).filter(BLUR) as background:  # pyright: ignore[reportUnknownMemberType]
        gradient = make_gradient_overlay(SIZE, theme)

        background.alpha_composite(gradient)
        background.alpha_composite(DARK_OVERLAY)

        background.paste(cover, (0, 0), cover)
        background.paste(SPOTIFY_LOGO, (WIDTH - LOGO_WIDTH - PADDING, PADDING), SPOTIFY_LOGO)

        title_truncated = truncate(activity.title, LARGE_FONT)
        artists_truncated = truncate(", ".join(activity.artists), MEDIUM_FONT)
        with Writer(background) as w:
            w.draw_text(title_truncated, CONTENT_X, PADDING, LARGE, FONT, TEXT_COLOR, stroke=1.5, stroke_color=STROKE_COLOR)
            w.draw_text(
                artists_truncated,
                CONTENT_X,
                PADDING + LARGE + 5,
                MEDIUM,
                FONT,
                TEXT_COLOR,
                stroke=1.5,
                stroke_color=STROKE_COLOR,
            )

            if activity.title.casefold() != activity.album.casefold():
                album_truncated = truncate(activity.album, MEDIUM_FONT)
                w.draw_text(
                    album_truncated,
                    CONTENT_X,
                    PADDING + LARGE + MEDIUM + 10,
                    MEDIUM,
                    FONT,
                    TEXT_COLOR,
                    stroke=1.5,
                    stroke_color=STROKE_COLOR,
                )

        return background, theme


@afunc()
def render_progress(static: Image.Image, activity: discord.Spotify, theme: Theme, /) -> BytesIO:
    seconds = activity.duration.total_seconds()
    progress = max(0.0, min(1.0, 1 - ((activity.end - discord.utils.utcnow()).total_seconds() / seconds)))
    played = BAR_X + int(progress * BAR_WIDTH)
    time_on = time_from_seconds(int(seconds * progress))
    time_end = time_from_seconds(int(seconds))

    with static.copy() as img:
        draw = ImageDraw.Draw(img)

        draw.rectangle((BAR_X, BAR_Y, BAR_LENGTH, BAR_Y + BAR_HEIGHT), tuple(int(c * 0.25) for c in theme.accent))
        draw.rectangle((BAR_X, BAR_Y, played, BAR_Y + BAR_HEIGHT), theme.accent)

        with Writer(img) as w:
            w.draw_text(
                f"{time_on} / {time_end}", BAR_X, BAR_TEXT_Y, SMALL, FONT, TEXT_COLOR, stroke=1.5, stroke_color=STROKE_COLOR
            )

    buf = BytesIO()
    img.save(buf, "PNG")
    buf.seek(0)
    return buf


async def render(session: aiohttp.ClientSession, activity: discord.Spotify, /) -> BytesIO:
    image_bytes = await get_image_bytes(session, activity.album_cover_url)
    static, theme = await render_static(image_bytes, activity)
    log.trace("%s", str(theme))
    return await render_progress(static, activity, theme)


async def send_spotify_embed(itx: Interaction, mention: str, activity: discord.Spotify) -> None:
    image = await render(itx.client.session, activity)
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


@app_commands.command(name="spotify", description="Get Spotify info in a stylish embed")
@app_commands.describe(user="The user to check. You by default")
@app_commands.checks.cooldown(1, 5.0, key=lambda i: i.user.id)
@app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
async def get_spotify(itx: Interaction, user: (discord.Member | discord.User) | None = None) -> None:
    assert itx.guild is not None, "This is a guild only command"

    user = itx.user if user is None else user
    member = itx.guild.get_member(user.id)

    if member is None:
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
