from . import _typings as t
from .bot import Interaction


def cf_ac_cache_transform(
    args: tuple[Interaction, str], kwds: t.Mapping[str, object]
) -> tuple[tuple[int, str], t.Mapping[str, object]]:
    itx, current = args
    assert itx.guild is not None, "Used in guild only commands"
    return (itx.guild.id, current.casefold()), kwds
