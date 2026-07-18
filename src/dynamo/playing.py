from __future__ import annotations

import datetime
import math
import operator
from io import BytesIO

import aiohttp
import discord
from async_utils.corofunc_cache import lrucorocache
from async_utils.task_cache import lrutaskcache
from discord import app_commands, ui
from discord.enums import ActivityType
from imagetext_py import Color as FontColor
from imagetext_py import FontDB, Paint, Writer
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageStat

from . import _typings as t
from ._ac import cf_ac_cache_transform
from ._types import BotExports
from .bot import Interaction
from .color import Color, luminance, saturation
from .logs import Logger, get_logger
from .services import MusicPresenceService, get_cached_bytes
from .utils import ROOT, afunc, human_join

log: Logger = get_logger(__name__)

FONT_PATH = ROOT / "assets" / "fonts"
FontDB.LoadFromDir(str(FONT_PATH))
FONT = FontDB.Query(" ".join(font.stem for font in FONT_PATH.rglob("*.ttf")))

LARGE = 42
MEDIUM = 28
SMALL = 24

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

DARK_OVERLAY = Image.new("RGBA", SIZE, (0, 0, 0, 64))


class Theme(t.NamedTuple):
    bg: tuple[int, int, int]
    accent: tuple[int, int, int]
    accent_alt: tuple[int, int, int]
    dominant: tuple[int, int, int]
    brightness: float
    is_dark: bool

    @classmethod
    def from_image(cls: type[Theme], image: Image.Image, /) -> Theme:
        palette = extract_palette(image)
        brightness = get_brightness(image)
        accent = max(palette, key=saturation)

        return Theme(
            palette[0],
            accent,
            min(palette, key=luminance),
            get_dominant_color(image),
            brightness,
            brightness < 0.5,
        )


class Track(t.NamedTuple):
    title: str | None
    artists: tuple[str, ...]
    album: str | None
    cover_url: str | None
    end: datetime.datetime | None
    duration: datetime.timedelta | None
    url: str | None
    player_name: str | None

    @classmethod
    def from_spotify(cls: type[Track], activity: discord.Spotify, /) -> Track:
        return Track(
            title=activity.title,
            artists=tuple(activity.artists),
            album=activity.album,
            cover_url=activity.album_cover_url,
            end=activity.end,
            duration=activity.duration,
            url=activity.track_url,
            player_name="Spotify",
        )

    @classmethod
    def from_activity(cls: type[Track], activity: discord.Activity, /) -> Track:
        start, end = activity.start, activity.end
        return Track(
            title=activity.details,
            artists=tuple(activity.state.split(", ")) if activity.state is not None else (),
            album=None,
            cover_url=activity.large_image_url,
            end=end,
            duration=end - start if end is not None and start is not None else None,
            url=activity.details_url,
            player_name=activity.name,
        )


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


def track_cache_transform(
    args: tuple[bytes, Track, bytes], kwargs: t.Mapping[str, object]
) -> tuple[tuple[str, tuple[str, ...], str, str], t.Mapping[str, object]]:
    _album_cover, track, _player_logo = args
    return (
        (
            track.title or "n/a",
            track.artists,
            track.album or "n/a",
            track.cover_url or "n/a",
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


@lrutaskcache(maxsize=50, cache_transform=track_cache_transform)
@afunc()
def render_static(image_bytes: bytes, track: Track, logo_bytes: bytes | None, /) -> tuple[bytes, Theme]:
    with Image.open(BytesIO(image_bytes)) as img:
        cover = img.convert("RGBA").resize(ALBUM_SIZE)  # pyright: ignore[reportUnknownMemberType]
        full = img.convert("RGB")

    theme = Theme.from_image(full)
    logo: Image.Image | None = None
    if logo_bytes is not None:
        logo = Image.open(BytesIO(logo_bytes)).resize(LOGO_SIZE)  # pyright: ignore[reportUnknownMemberType]

    with cover.convert("RGBA").resize(SIZE).filter(BLUR) as background:  # pyright: ignore[reportUnknownMemberType]
        gradient = make_gradient_overlay(SIZE, theme)

        background.alpha_composite(gradient)
        background.alpha_composite(DARK_OVERLAY)

        background.paste(cover, (0, 0), cover)
        if logo is not None:
            background.paste(logo, (WIDTH - LOGO_WIDTH - PADDING, PADDING), logo)

        title = track.title or "A track"
        title_truncated = truncate(title, LARGE_FONT)
        artists_truncated = truncate(", ".join(track.artists), MEDIUM_FONT)
        with Writer(background) as w:
            w.draw_text(title_truncated, CONTENT_X, PADDING, LARGE, FONT, TEXT_COLOR)
            w.draw_text(artists_truncated, CONTENT_X, PADDING + LARGE + 5, MEDIUM, FONT, TEXT_COLOR)

            if track.album is not None and title.casefold() != track.album.casefold():
                album_truncated = truncate(track.album, MEDIUM_FONT)
                w.draw_text(album_truncated, CONTENT_X, PADDING + LARGE + MEDIUM + 10, MEDIUM, FONT, TEXT_COLOR)

        buf = BytesIO()
        background.save(buf, "PNG")
        return buf.getvalue(), theme


@afunc()
def render_progress(static_bytes: bytes, duration: datetime.timedelta, end: datetime.datetime, theme: Theme, /) -> BytesIO:
    seconds = duration.total_seconds()
    progress = max(0.0, min(1.0, 1 - ((end - discord.utils.utcnow()).total_seconds() / seconds)))
    played = BAR_X + int(progress * BAR_WIDTH)
    time_on = time_from_seconds(int(seconds * progress))
    time_end = time_from_seconds(int(seconds))

    with Image.open(BytesIO(static_bytes)).copy() as img:
        draw = ImageDraw.Draw(img)

        draw.rectangle((BAR_X, BAR_Y, BAR_LENGTH, BAR_Y + BAR_HEIGHT), tuple(int(c * 0.25) for c in theme.accent))
        draw.rectangle((BAR_X, BAR_Y, played, BAR_Y + BAR_HEIGHT), theme.accent)

        with Writer(img) as w:
            w.draw_text(f"{time_on} / {time_end}", BAR_X, BAR_TEXT_Y, SMALL, FONT, TEXT_COLOR)

    buf = BytesIO()
    img.save(buf, "PNG")
    buf.seek(0)
    return buf


async def render(
    session: aiohttp.ClientSession, service: MusicPresenceService, track: Track, /
) -> tuple[BytesIO, tuple[int, int, int]]:
    log.debug("%s", track)
    track_cover_bytes = await get_cached_bytes(session, track.cover_url) if track.cover_url is not None else None
    player_logo_bytes = None
    try:
        player_logo_bytes = await service.get_icon(track.player_name) if track.player_name is not None else None
    except aiohttp.ClientResponseError:
        log.warning("Could not get logo, defaulting to no logo.")
    if track_cover_bytes is None:
        msg = f"Couldn't get track cover for track {track!r}"
        raise RuntimeError(msg)
    static_bytes, theme = await render_static(track_cover_bytes, track, player_logo_bytes)
    if track.duration is not None and track.end is not None:
        return await render_progress(static_bytes, track.duration, track.end, theme), theme.accent

    buf = BytesIO(static_bytes)
    buf.seek(0)
    return buf, theme.accent


def find_spotify(activities: tuple[discord.activity.ActivityTypes, ...], /) -> Track | None:
    spotify = next((a for a in activities if isinstance(a, discord.Spotify)), None)
    return Track.from_spotify(spotify) if spotify is not None else None


def find_track(activities: tuple[discord.activity.ActivityTypes, ...], application_ids: frozenset[int], /) -> Track | None:
    activity = next(
        (
            a
            for a in activities
            if isinstance(a, discord.Activity) and a.type == ActivityType.listening
            # and a.application_id in application_ids
        ),
        None,
    )
    return Track.from_activity(activity) if activity is not None else None


async def get_players(service: MusicPresenceService, /) -> dict[str, int]:
    players = await service.get_players()

    result: dict[str, int] = {}
    for player in players["players"]:
        if "discord_application_id" in player["extra"]:
            result[player["name"]] = int(player["extra"]["discord_application_id"])

    return result


@app_commands.command(name="playing", description="Show off what you're listening to")
@app_commands.describe(
    user="The user to check. You by default",
    player="The activity to show. If empty, try get Spotify or the first listening activity listed",
)
@app_commands.checks.cooldown(1, 5.0, key=lambda i: i.user.id)
@app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
async def get_playing(
    itx: Interaction, user: discord.Member | discord.User | None = None, player: str | None = None
) -> None:
    assert itx.guild is not None, "This is a guild only command"

    user = itx.user if user is None else user
    member = itx.guild.get_member(user.id)

    if member is None:
        await itx.response.send_message("That member is not in this guild.", ephemeral=True)
        return

    track: Track | None = None
    if player is None:
        track = find_spotify(member.activities)
        if track is None:
            ids = frozenset((await get_players(itx.client.services.music_presence)).values())
            track = find_track(member.activities, ids)
    else:
        track = find_track(member.activities, frozenset((int(player),)))

    if track is None:
        prefix = "You are" if user.id == itx.user.id else f"{user!s} is"
        suffix = "anything" if player is None else "that"
        await itx.response.send_message(f"{prefix} not listening to {suffix}", ephemeral=True)
        return

    await itx.response.defer()
    image, accent = await render(itx.client.session, itx.client.services.music_presence, track)

    c = ui.Container[ui.LayoutView](accent_color=Color.from_rgb(*accent))
    track_name = track.title if track.url is None else f"[{track.title}]({track.url})"
    artists = human_join(track.artists)
    c.add_item(ui.TextDisplay(f"### {user.mention} is listening to **{track_name}** by **{artists}**"))
    file = discord.File(image, "playing.png")
    c.add_item(ui.MediaGallery(discord.MediaGalleryItem(file)))

    view = ui.LayoutView()
    view.add_item(c)

    await itx.followup.send(view=view, file=file)


@get_playing.autocomplete("player")
@lrucorocache(300, cache_transform=cf_ac_cache_transform)
async def autocomplete(itx: Interaction, current: str, /) -> list[app_commands.Choice[str]]:
    assert itx.guild is not None, "Guild only transformer"
    cf_current = current.casefold()
    all_players = await get_players(itx.client.services.music_presence)
    player_matches = ((p, p_id) for p, p_id in all_players.items() if p.casefold().startswith(cf_current))
    players = sorted(player_matches, key=operator.itemgetter(0))[:25]
    return [app_commands.Choice(name=p, value=str(p_id)) for p, p_id in players]


exports: BotExports = BotExports(commands=[get_playing])
