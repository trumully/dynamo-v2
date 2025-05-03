from __future__ import annotations

import re

import discord
from async_utils.corofunc_cache import lrucorocache
from discord.app_commands import Choice, Transformer, TransformerError

from dynamo._ac import ac_cache_transform_guild
from dynamo.bot import Dynamo, Interaction

from .logs import get_logger

_ID_REGEX = re.compile(r"([0-9]{15,20})$")


log = get_logger(__name__)
evt_log = log.getChild("EventTransformer")


def ac_cache_transformer_guild(
    args: tuple[EventTransformer, Interaction, str], kwds: dict[str, object]
) -> tuple[tuple[int, str], dict[str, object]]:
    _transformer, itx, current = args
    return ac_cache_transform_guild((itx, current), kwds)


class IDTransformer(Transformer[Dynamo]):
    @staticmethod
    def _get_id_match(value: str, /) -> re.Match[str] | None:
        return _ID_REGEX.match(value)


class EventTransformer(IDTransformer):
    async def transform(self, itx: Interaction, value: str, /) -> discord.ScheduledEvent:
        guild = itx.guild
        assert guild is not None, "Guild only transformer."

        result: discord.ScheduledEvent | None = None

        # ID match
        if (match := self._get_id_match(value)) is not None:
            evt_log.trace("Got ID match for %s", value)
            event_id = int(match.group(1))
            result = guild.get_scheduled_event(event_id)
        else:
            pattern = (
                r"https?://(?:(ptb|canary|www)\.)?discord\.com/events/"
                r"(?P<guild_id>[0-9]{15,20})/"
                r"(?P<event_id>[0-9]{15,20})$"
            )
            # URL match
            if (match := re.match(pattern, value, flags=re.IGNORECASE)) is not None:
                evt_log.trace("Got URL match for %s", value)
                guild = itx.client.get_guild(int(match.group("guild_id")))
                if guild is not None:
                    event_id = int(match.group("event_id"))
                    result = guild.get_scheduled_event(event_id)
            else:
                # Lookup by name
                evt_log.trace("Trying lookup by name with %s", value)
                result = discord.utils.get(guild.scheduled_events, name=value)

        if result is None:
            raise TransformerError(value, self.type, self) from None

        return result

    @lrucorocache(cache_transform=ac_cache_transformer_guild)
    async def autocomplete(self, itx: Interaction, current: str, /) -> list[Choice[str]]:  # type: ignore[reportIncompatibleMethodOverride]  # noqa: PLR6301
        assert itx.guild is not None, "Guild only transformer."
        events = itx.guild.scheduled_events[:25]
        return [Choice(name=e.name, value=str(e.id)) for e in events if current in e.name]
