from __future__ import annotations

from enum import StrEnum
from functools import partial

import discord
from async_utils.task_cache import lrutaskcache
from discord import ScheduledEvent, app_commands
from discord.app_commands import Transform
from discord.asset import VALID_ASSET_FORMATS, VALID_STATIC_FORMATS
from discord.components import SelectOption
from discord.enums import ButtonStyle

from ._typings import BotExports, DynButton, DynSelect
from .bot import Interaction
from .logs import Logger, get_logger
from .utils import b2048pack, b2048unpack
from .utils.transformer import EventTransformer

log: Logger = get_logger(__name__)


class Asset(StrEnum):
    AVATAR = "avatar"
    BANNER = "banner"
    DECORATION = "decoration"


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

AssetData = tuple[str, int, int, Asset, Format, int]


def _fetch_banner_transform(
    args: tuple[Interaction, discord.Member | discord.User], kwds: dict[str, object]
) -> tuple[tuple[int], dict[str, object]]:
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
        user_name: str,
        asset_url: str,
        image_kind: str,
        file_type: Format,
        size: int,
    ) -> discord.Embed:
        e = discord.Embed(title=f"{user_name}'s {image_kind.lower()}")
        e.add_field(name="Format", value=file_type)
        e.add_field(name="Size", value=size)
        e.set_image(url=asset_url)
        return e

    @classmethod
    async def start(cls, itx: Interaction, user_id: int, target_id: int) -> None:
        await cls.set_asset(itx, user_id, target_id, initial=True)

    @classmethod
    async def set_asset(
        cls,
        itx: Interaction,
        user_id: int,
        target_id: int,
        image_kind: Asset = Asset.AVATAR,
        file_type: Format = Format.PNG,
        size: int = 512,
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

        if image_kind is Asset.AVATAR:
            asset = user.display_avatar
        elif image_kind is Asset.BANNER:
            asset = banner
        else:
            asset = user.avatar_decoration

        has_no_banner = banner is None
        has_no_decoration = user.avatar_decoration is None

        assert asset is not None, "Button is disabled when the asset does not exist"
        is_animated = asset.is_animated()
        asset = asset.with_format(file_type.value).with_size(size)

        embed = cls.setup(user.name, asset.url, image_kind, file_type, size)

        v = discord.ui.View()

        c_id = cls.custom_id("avatar", user_id, target_id, Asset.AVATAR, "png", size)
        v.add_item(DynButton(label="Avatar", custom_id=c_id))

        c_id = cls.custom_id("banner", user_id, target_id, Asset.BANNER, "png", size)
        v.add_item(DynButton(label="Banner", custom_id=c_id, disabled=has_no_banner))

        c_id = cls.custom_id("deco", user_id, target_id, Asset.DECORATION, "png", size)
        v.add_item(DynButton(label="Decoration", custom_id=c_id, disabled=has_no_decoration))
        if is_animated:
            text = "This asset is animated. "
            if image_kind is Asset.DECORATION:
                text += "Set format to .png and open in browser to view."
            else:
                text += "Set format to .gif to view."
            embed.set_footer(text=text)

        v.add_item(DynButton(label="View", url=asset.url, style=ButtonStyle.url))

        c_id = cls.custom_id("format", user_id, target_id, image_kind, file_type, size)
        opts = (
            ASSET_FORMAT_OPTIONS
            if is_animated and image_kind is not Asset.DECORATION
            else STATIC_FORMAT_OPTIONS
        )
        v.add_item(DynSelect(placeholder="Set format", custom_id=c_id, options=opts))

        c_id = cls.custom_id("size", user_id, target_id, image_kind, file_type, size)
        v.add_item(DynSelect(placeholder="Change size", custom_id=c_id, options=SIZE_OPTIONS))

        method = send if initial else edit
        await method(embed=embed, view=v)

    @classmethod
    async def raw_submit(cls, itx: Interaction, data: str) -> None:
        op, user_id, target_id, kind, fmt, size = b2048unpack(data, AssetData)
        if itx.user.id != user_id:
            return

        assert itx.data is not None

        values: list[str] = itx.data.get("values", [])
        if values:
            changed = values[0]
            if op == "format":
                fmt = Format(changed) if changed in VALID_ASSET_FORMATS else Format.PNG
            elif op == "size":
                size = int(changed) if discord.utils.valid_icon_size(int(changed)) else 512

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
