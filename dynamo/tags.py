from __future__ import annotations

import discord
from async_utils.corofunc_cache import lrucorocache
from discord.app_commands import Choice, Group, Range, describe
from discord.ui import Modal, TextInput

from ._ac import ac_cache_transform
from ._typings import BotExports
from .bot import Interaction
from .utils.logic import b2048pack, b2048unpack

tag_group = Group(name="tag", description="Store and recall content")


class TagModal(Modal):
    tag: TextInput[TagModal] = TextInput(
        label="Tag", style=discord.TextStyle.paragraph, min_length=1, max_length=1000
    )

    def __init__(
        self,
        *,
        title: str = "Add tag",
        timeout: float | None = None,
        custom_id: str = "",
        tag_name: str,
        author_id: int,
    ) -> None:
        disc_safe = b2048pack((author_id, tag_name))
        custom_id = f"m:tag:{disc_safe}"
        super().__init__(title=title, timeout=10, custom_id=custom_id)

    @staticmethod
    async def raw_submit(itx: Interaction, data: str) -> None:
        author_id, tag_name = b2048unpack(data, tuple[int, str])

        assert itx.data, "Checked by caller"

        raw_ = itx.data.get("components", None)
        if not raw_:
            return
        comp = raw_[0]
        modal_components = comp.get("components")
        if not modal_components:
            return
        content = modal_components[0]["value"]
        with itx.client.conn:
            itx.client.conn.execute(
                """
                INSERT INTO user_tags (user_id, tag_name, content)
                VALUES (:author_id, :tag_name, :content)
                ON CONFLICT (user_id, tag_name)
                DO UPDATE SET content=excluded.content;
                """,
                {"author_id": author_id, "tag_name": tag_name, "content": content},
            )
        await itx.response.send_message(content="Tag created", ephemeral=True)


@tag_group.command(name="create", description="Create or replace tag content")
@describe(name="Name of created tag")
async def tag_create(itx: Interaction, name: Range[str, 1, 20]) -> None:
    modal = TagModal(tag_name=name, author_id=itx.user.id)
    await itx.response.send_modal(modal)


@tag_group.command(name="get", description="Get content of a tag")
@describe(name="The tag to get")
async def tag_get(itx: Interaction, name: Range[str, 1, 20]) -> None:
    content = itx.client.read_conn.execute(
        """
        SELECT content FROM user_tags
        WHERE user_id = ? AND tag_name = ? LIMIT 1;
        """,
        (itx.user.id, name),
    ).get

    if content is None:
        await itx.response.send_message(content="No such tag.", ephemeral=True)
    else:
        await itx.response.send_message(content)


@tag_group.command(name="delete", description="Delete a tag")
@describe(name="The tag to delete")
async def tag_del(itx: Interaction, name: Range[str, 1, 20]) -> None:
    await itx.response.defer(ephemeral=True)
    with itx.client.conn:
        row = itx.client.conn.execute(
            """
            DELETE FROM user_tags
            WHERE user_id = ? AND tag_name = ?
            RETURNING tag_name
            """,
            (itx.user.id, name),
        ).get
    msg = "No such tag" if row is None else "Tag deleted"
    await itx.edit_original_response(content=msg)


@tag_get.autocomplete("name")
@tag_del.autocomplete("name")
@lrucorocache(300, cache_transform=ac_cache_transform)
async def tag_ac(itx: Interaction, current: str) -> list[Choice[str]]:
    cursor = itx.client.read_conn.execute(
        """
        SELECT tag_name
        FROM user_tags
        WHERE user_id = ? AND tag_name LIKE ? || '%' LIMIT 25
        """,
        (itx.user.id, current),
    )
    return [Choice(name=name, value=name) for (name,) in cursor]


exports = BotExports([tag_group], {"tag": TagModal})
