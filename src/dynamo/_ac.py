from collections.abc import Mapping

from .bot import Interaction


def cf_ac_cache_transform(
    args: tuple[Interaction, str], kwds: Mapping[str, object]
) -> tuple[tuple[int, str], Mapping[str, object]]:
    itx, current = args
    assert itx.guild is not None, "Used in guild only commands"
    return (itx.guild.id, current.casefold()), kwds
