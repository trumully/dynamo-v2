from __future__ import annotations

from .bot import Interaction


def ac_cache_transform(
    args: tuple[Interaction, str], kwds: dict[str, object]
) -> tuple[tuple[int, str], dict[str, object]]:
    itx, current = args
    return (itx.user.id, current), kwds


def ac_cache_transform_guild(
    args: tuple[Interaction, str], kwds: dict[str, object]
) -> tuple[tuple[int, str], dict[str, object]]:
    itx, current = args
    assert itx.guild is not None, "Should only be used in guild only commands"
    return (itx.guild.id, current), kwds
