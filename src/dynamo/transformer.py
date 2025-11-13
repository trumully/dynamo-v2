from __future__ import annotations

import re
from collections.abc import Mapping

import discord
from discord import app_commands
from discord.app_commands import Choice

from dynamo import _typing as t
from dynamo.bot import Dynamo, Interaction
from dynamo.logs import Logger, get_logger

_ID_REGEX = re.compile(r"([0-9]{15,20})$")

_URL_PATTERN = (
    r"https?://(?:(ptb|canary|www)\.)?discord\.com/events/"
    r"(?P<guild_id>[0-9]{15,20})/"
    r"(?P<event_id>[0-9]{15,20})$"
)

log: Logger = get_logger(__name__)
evt_log: Logger = log.getChild("EventTransformer")


class Transformer(app_commands.Transformer[Dynamo]):
    @staticmethod
    def ac_cache_transformer(
        args: tuple[t.Any, ...], kwds: Mapping[str, t.Any]
    ) -> tuple[tuple[t.Any, ...], Mapping[str, t.Any]]:
        """Cache results for the transformer's autocomplete method"""
        msg = "Derived classes will implement this"
        raise NotImplementedError(msg)


class EventTransformer(Transformer):
    @t.override
    async def transform(self, itx: Interaction, value: str, /) -> discord.ScheduledEvent:
        guild = itx.guild
        assert guild is not None, "Guild only transformer."

        result: discord.ScheduledEvent | None = None

        # ID match
        if match := _ID_REGEX.match(value):
            evt_log.trace("Got ID match for %s", value)
            event_id = int(match.group(1))
            result = guild.get_scheduled_event(event_id)
        # URL match
        elif match := re.match(_URL_PATTERN, value, re.IGNORECASE):
            evt_log.trace("Got URL match for %s", value)
            if int(match.group("guild_id")) == guild.id:
                event_id = int(match.group("event_id"))
                result = guild.get_scheduled_event(event_id)
        # Lookup by name
        else:
            evt_log.trace("Trying lookup by name with %s", value)
            result = discord.utils.get(guild.scheduled_events, name=value)

        if result is None:
            raise app_commands.TransformerError(value, self.type, self) from None

        return result

    @t.override
    async def autocomplete(self, itx: Interaction, current: str, /) -> list[Choice[str]]:  # pyright: ignore[reportIncompatibleMethodOverride]
        assert itx.guild is not None, "Guild only transformer."
        events = itx.guild.scheduled_events[:25]
        return [Choice(name=e.name, value=str(e.id)) for e in events if current in e.name]
