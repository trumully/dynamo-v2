from __future__ import annotations

import logging

from discord import AppCommandOptionType
from discord.app_commands import Transformer

from dynamo import _typing_shim as t
from dynamo.bot import Interaction

if t.TYPE_CHECKING:
    from dynamo.bot import Dynamo  # noqa: F401

log = logging.getLogger(__name__)


class CleanString(Transformer["Dynamo"]):
    async def transform(self, itx: Interaction, value: str, /) -> str:  # noqa: PLR6301
        return "".join(c for c in value if c.isalnum())

    @property
    def type(self) -> AppCommandOptionType:
        return AppCommandOptionType.string
