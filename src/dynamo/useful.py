from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from functools import partial

import discord
from async_utils.task_cache import lrutaskcache
from discord import ScheduledEvent, app_commands, components, ui
from discord.app_commands import Transform
from discord.asset import VALID_ASSET_FORMATS, VALID_STATIC_FORMATS
from discord.components import SelectOption
from discord.enums import ButtonStyle

from ._types import BotExports, DynButton, DynContainer, DynRow, DynSelect
from .bot import Interaction
from .logs import Logger, get_logger
from .transformer import EventTransformer
from .utils import b2048pack, b2048unpack

log: Logger = get_logger(__name__)


class Asset(StrEnum):
    AVATAR = "avatar"
    BANNER = "banner"
    DECO = "decoration"


class Format(StrEnum):
    WEBP = "webp"
    PNG = "png"
    JPG = "jpg"
    JPEG = "jpeg"
    GIF = "gif"


VALID_SIZES = (16, 32, 64, 128, 256, 512, 1024, 2048, 4096)

SIZE_OPTIONS = [SelectOption(label=str(i)) for i in VALID_SIZES]
STATIC_FORMAT_OPTIONS = [SelectOption(label="." + f, value=f) for f in VALID_STATIC_FORMATS]
ASSET_FORMAT_OPTIONS = [SelectOption(label="." + f, value=f) for f in VALID_ASSET_FORMATS]

# "mostly" the defaults
DEFAULT_SIZE = 1024
DEFAULT_FORMAT = Format.PNG

DEFAULT_ASSET = Asset.AVATAR

AssetData = tuple[str, int, int, Asset, Format, int]

MISSING = discord.utils.MISSING


def _fetch_banner_transform(
    args: tuple[Interaction, discord.Member | discord.User], kwds: Mapping[str, object]
) -> tuple[tuple[int], Mapping[str, object]]:
    _itx, user = args
    return (user.id,), kwds


@lrutaskcache(cache_transform=_fetch_banner_transform)
async def fetch_banner(
    itx: Interaction, user: discord.Member | discord.User
) -> discord.Asset | None:
    """Fetch a banner from a member or user.

    Due to a bug in dpy, the fallback for `discord.Member.display_banner` is always `None`.
    https://discord.com/channels/336642139381301249/1342075560498823198/1342075560498823198
    """

    if not isinstance(user, discord.Member):
        log.trace("Got banner from user %s", user)
        return user.banner
    if (display_banner := user.display_banner) is not None:
        log.trace("Got display banner from user %s", user)
        return display_banner
    log.trace("Got banner from fetched user %s", user)
    return (await itx.client.fetch_user(user.id)).banner


class AssetView:
    @staticmethod
    def custom_id(*to_pack: object) -> str:
        return "c:asset:" + b2048pack(to_pack)

    @staticmethod
    def setup(
        name: str,
        url: str,
        kind: Asset,
        fmt: Format,
        size: int,
        *,
        is_animated: bool = False,
    ) -> DynContainer:
        text = f"# {name}'s {kind.lower()}"
        text += f"\n**Format:** `{fmt}`       |       **Size:** `{size}`"
        if is_animated:
            text += f"\n-# This {kind.value} is animated; "
            if kind is Asset.DECO:
                text += "select `png` format and `Open in browser` to view."
            else:
                text += "select `gif` format to view."
        return DynContainer(
            ui.TextDisplay(text),
            ui.MediaGallery(components.MediaGalleryItem(url)),
            ui.Separator(visible=False),
        )

    @classmethod
    async def start(cls, itx: Interaction, user_id: int, target_id: int) -> None:
        await cls.set_asset(itx, user_id, target_id, initial=True)

    @classmethod
    async def set_asset(
        cls,
        itx: Interaction,
        user_id: int,
        target_id: int,
        image_kind: Asset = DEFAULT_ASSET,
        file_type: Format = DEFAULT_FORMAT,
        size: int = DEFAULT_SIZE,
        *,
        initial: bool = False,
        deferred: bool = False,
    ) -> None:
        if itx.guild is not None:
            user = itx.guild.get_member(target_id)
        else:
            user = await itx.client.fetch_user(target_id)

        assert user is not None, "This view is opened from a member context."
        edit = itx.edit_original_response if deferred else itx.response.edit_message
        send = edit if deferred else partial(itx.response.send_message, ephemeral=True)

        banner = await fetch_banner(itx, user)
        avatar = user.display_avatar
        decoration = user.avatar_decoration

        if image_kind is Asset.AVATAR:
            asset = avatar
        elif image_kind is Asset.BANNER:
            asset = banner
        elif image_kind is Asset.DECO:
            asset = decoration

        assert asset is not None, "Button is disabled when the asset does not exist"
        has_no_banner = banner is None
        has_no_decoration = decoration is None
        is_animated = asset.is_animated()

        if file_type is not DEFAULT_FORMAT:
            asset = asset.with_format(file_type.value)
        if size != DEFAULT_SIZE:
            asset = asset.with_size(size)

        c = cls.setup(user.name, asset.url, image_kind, file_type, size, is_animated=is_animated)

        btns = DynRow()

        avatar_format = "gif" if avatar.is_animated() else "png"
        c_id = cls.custom_id("avatar", user_id, target_id, Asset.AVATAR, avatar_format, size)
        btn = DynButton(
            label="Avatar",
            custom_id=c_id,
            style=ButtonStyle.blurple,
            disabled=image_kind is Asset.AVATAR,
        )
        btns.add_item(btn)

        banner_format = "gif" if not has_no_banner and banner.is_animated() else "png"
        c_id = cls.custom_id("banner", user_id, target_id, Asset.BANNER, banner_format, size)
        btn = DynButton(
            label="Banner",
            custom_id=c_id,
            style=ButtonStyle.blurple,
            disabled=has_no_banner or image_kind is Asset.BANNER,
        )
        btns.add_item(btn)

        # Animated decorations are an animated png so use png no matter what
        c_id = cls.custom_id("deco", user_id, target_id, Asset.DECO, "png", size)
        btn = DynButton(
            label="Decoration",
            custom_id=c_id,
            style=ButtonStyle.blurple,
            disabled=has_no_decoration or image_kind is Asset.DECO,
        )
        btns.add_item(btn)
        btns.add_item(DynButton(label="View", url=asset.url, style=ButtonStyle.url))

        c.add_item(btns).add_item(ui.Separator(visible=False))

        c_id = cls.custom_id("format", user_id, target_id, image_kind, file_type, size)
        row = DynRow()
        options = (
            ASSET_FORMAT_OPTIONS
            if is_animated and image_kind is not Asset.DECO
            else STATIC_FORMAT_OPTIONS
        )
        row.add_item(DynSelect(placeholder="Set format", custom_id=c_id, options=options))
        c.add_item(row)

        c_id = cls.custom_id("size", user_id, target_id, image_kind, file_type, size)
        row = DynRow()
        row.add_item(DynSelect(placeholder="Change size", custom_id=c_id, options=SIZE_OPTIONS))
        c.add_item(row)

        method = send if initial else edit
        await method(view=ui.LayoutView().add_item(c))

    @classmethod
    async def raw_submit(cls, itx: Interaction, data: str) -> None:
        op, user_id, target_id, kind, fmt, size = b2048unpack(data, AssetData)
        if itx.user.id != user_id:
            return

        assert itx.data is not None

        values: list[str] = itx.data.get("values", [])
        if values:
            if op == "format":
                fmt = Format(values[0])
            elif op == "size":
                size = int(values[0])

        await itx.response.defer(ephemeral=True)
        await cls.set_asset(itx, user_id, target_id, kind, fmt, size, deferred=True)


@app_commands.context_menu(name="View assets")
async def get_assets(itx: Interaction, user: discord.Member | discord.User) -> None:
    view = AssetView()
    await view.start(itx, itx.user.id, user.id)


@app_commands.command(name="interested", description="Get event hyperlink with list of attendees")
@app_commands.describe(event="The name of the event", ephemeral="Send privately")
@app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
async def interested(
    itx: Interaction,
    event: Transform[ScheduledEvent, EventTransformer],
    ephemeral: bool = True,
) -> None:
    assert itx.guild is not None, "This is a guild only command"

    users_interested = " ".join([u.mention async for u in event.users()])
    content = f"`[{event.name}]({event.url}) {users_interested or 'None interested'}`"

    await itx.response.send_message(content=content, ephemeral=ephemeral)


exports: BotExports = BotExports(
    commands=[interested, get_assets], raw_component_submits={"asset": AssetView}
)
