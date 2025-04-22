import logging
from enum import StrEnum
from functools import partial

import discord
from async_utils.task_cache import lrutaskcache
from discord import app_commands
from discord.components import SelectOption
from discord.enums import ButtonStyle

from ._typings import BotExports, CoroFunc, DynButton, DynSelect
from .bot import Interaction
from .utils.logic import b2048pack, b2048unpack

log = logging.getLogger(__name__)


class Asset(StrEnum):
    AVATAR = "avatar"
    BANNER = "banner"
    DECORATION = "decoration"


class Format(StrEnum):
    WEBP = "webp"
    PNG = "png"
    JPEG = "jpeg"
    GIF = "gif"


VALID_SIZES = (16, 32, 64, 128, 256, 512, 1024, 2048, 4096)
STATIC_FORMATS = frozenset({"webp", "png", "jpeg"})
ALL_FORMATS = STATIC_FORMATS | {"gif"}

SIZE_OPTIONS = [SelectOption(label=str(i)) for i in VALID_SIZES]
STATIC_FORMAT_OPTIONS = [SelectOption(label="." + f, value=f) for f in STATIC_FORMATS]
ALL_FORMAT_OPTIONS = [SelectOption(label="." + f, value=f) for f in ALL_FORMATS]

AssetData = tuple[str, int, int, Asset, Format, int]


def _cache_transform(
    args: tuple[discord.Member | discord.User, CoroFunc[[int], discord.User]],
    kwds: dict[str, object],
) -> tuple[tuple[int], dict[str, object]]:
    user, _fetch = args
    return (user.id,), kwds


@lrutaskcache(cache_transform=_cache_transform)
async def fetch_banner(
    user: discord.Member | discord.User, fetch: CoroFunc[[int], discord.User]
) -> discord.Asset | None:
    """Fetch a banner from a member or user.

    Due to a bug in dpy, the fallback for `discord.Member.display_banner` is always `None`.
    https://discord.com/channels/336642139381301249/1342075560498823198/1342075560498823198
    """
    if not isinstance(user, discord.Member):
        return user.banner
    if (display_banner := user.display_banner) is not None:
        return display_banner
    return (await fetch(user.id)).banner


class AssetView:
    @staticmethod
    def setup(
        user_name: str,
        asset_url: str,
        asset_kind: Asset,
        asset_format: Format,
        asset_size: int,
    ) -> discord.Embed:
        e = discord.Embed(title=f"{user_name}'s {asset_kind.lower()}")
        e.add_field(name="Format", value=asset_format)
        e.add_field(name="Size", value=asset_size)
        e.set_image(url=asset_url)
        return e

    @classmethod
    async def start(
        cls,
        itx: Interaction,
        user_id: int,
        target_id: int,
    ) -> None:
        await cls.set_asset(itx, user_id, target_id, initial=True)

    @classmethod
    async def set_asset(
        cls,
        itx: Interaction,
        user_id: int,
        target_id: int,
        asset_kind: Asset = Asset.AVATAR,
        asset_format: Format = Format.PNG,
        asset_size: int = 256,
        *,
        initial: bool = False,
        deferred: bool = False,
    ) -> None:
        if itx.guild is None:
            user = await itx.client.fetch_user(target_id)
        else:
            user = itx.guild.get_member(target_id)
            assert user is not None, "This is a member context menu, this is always true."

        edit = itx.edit_original_response if deferred else itx.response.edit_message
        send = edit if deferred else partial(itx.response.send_message, ephemeral=True)

        banner = await fetch_banner(user, itx.client.fetch_user)
        if asset_kind is Asset.AVATAR:
            asset = user.display_avatar
        elif asset_kind is Asset.BANNER:
            asset = banner
        else:
            asset = user.avatar_decoration

        has_no_banner = banner is None
        has_no_decoration = user.avatar_decoration is None

        assert asset is not None, "Button is disabled when the asset does not exist"
        is_animated = asset.is_animated()
        asset = asset.with_format(asset_format.value).with_size(asset_size)

        embed = cls.setup(user.name, asset.url, asset_kind, asset_format, asset_size)

        v = discord.ui.View()

        c_id = "c:asset:" + b2048pack((
            "avatar",
            user_id,
            target_id,
            Asset.AVATAR,
            Format.PNG,
            asset_size,
        ))
        v.add_item(DynButton(label="Avatar", custom_id=c_id))

        c_id = "c:asset:" + b2048pack((
            "banner",
            user_id,
            target_id,
            Asset.BANNER,
            Format.PNG,
            asset_size,
        ))
        v.add_item(DynButton(label="Banner", custom_id=c_id, disabled=has_no_banner))

        c_id = "c:asset:" + b2048pack((
            "deco",
            user_id,
            target_id,
            Asset.DECORATION,
            Format.PNG,
            asset_size,
        ))
        v.add_item(
            DynButton(label="Decoration", custom_id=c_id, disabled=has_no_decoration)
        )
        if is_animated and asset_kind is Asset.DECORATION and asset_format is Format.PNG:
            embed.set_footer(
                text="This decoration is an animated png (APNG). "
                " Open the image outside of Discord to view it."
            )

        v.add_item(DynButton(label="View", url=asset.url, style=ButtonStyle.url))

        c_id = "c:asset:" + b2048pack((
            "format",
            user_id,
            target_id,
            asset_kind,
            asset_format,
            asset_size,
        ))
        opts = (
            ALL_FORMAT_OPTIONS
            if is_animated and asset_kind is not Asset.DECORATION
            else STATIC_FORMAT_OPTIONS
        )
        v.add_item(DynSelect(placeholder="Change format", custom_id=c_id, options=opts))

        c_id = "c:asset:" + b2048pack((
            "size",
            user_id,
            target_id,
            asset_kind,
            asset_format,
            asset_size,
        ))
        v.add_item(
            DynSelect(placeholder="Change size", custom_id=c_id, options=SIZE_OPTIONS)
        )

        method = send if initial else edit
        await method(embed=embed, view=v)

    @classmethod
    async def raw_submit(cls, itx: Interaction, data: str) -> None:
        op, user_id, target_id, kind, fmt, size = b2048unpack(data, AssetData)
        if itx.user.id != user_id:
            return

        assert itx.data is not None

        if op == "format":
            value: list[str] = itx.data.get("values", [])
            fmt = Format(value[0]) if value else Format.PNG

        if op == "size":
            value: list[str] = itx.data.get("values", [])
            size = int(value[0]) if value else 256

        await itx.response.defer(ephemeral=True)
        await cls.set_asset(itx, user_id, target_id, kind, fmt, size, deferred=True)


@app_commands.context_menu(name="View assets")
async def get_assets(itx: Interaction, user: discord.Member | discord.User) -> None:
    view = AssetView()
    await view.start(itx, itx.user.id, user.id)


exports = BotExports(commands=[get_assets], raw_component_submits={"asset": AssetView})
