from __future__ import annotations

import logging
import re
from collections.abc import Generator

import discord
from async_utils.lru import LRU
from discord import AppCommandOptionType, app_commands
from discord.app_commands import Transformer

from dynamo import _typings as t
from dynamo.bot import Interaction

if t.TYPE_CHECKING:
    from dynamo.bot import Dynamo  # noqa: F401

_ID_REGEX = re.compile(r"([0-9]{15,20})$")

log = logging.getLogger(__name__)


def _get_id_match(value: str) -> re.Match[str] | None:
    return _ID_REGEX.match(value)


_guild_events_cache: LRU[int, list[discord.ScheduledEvent]] = LRU(128)


def _get_cached_event(
    values: list[discord.ScheduledEvent],
    value: str,
    /,
) -> Generator[discord.ScheduledEvent]:
    return (
        e
        for e in values
        if e.name.casefold() == value.casefold()
        or str(e.id) == value
        or e.url.lower() == value.lower()
    )


class ScheduledEventTransformer(Transformer["Dynamo"]):
    """discord.ScheduledEvent transformer adapted from the discord.py converter.

    Lookups are done for the local guild if available. Otherwise, for a DM context,
    lookup is done by the global cache.

    The lookup strategy is as follows (in order):

    1. Lookup by ID.
    2. Lookup by url.
    3. Lookup by name.
    """

    async def transform(self, itx: Interaction, value: str, /) -> discord.ScheduledEvent:
        if itx.guild is None:
            msg = "Tried transforming event outside of guild"
            raise app_commands.NoPrivateMessage(msg) from None

        guild: discord.Guild | None = itx.guild
        events = _guild_events_cache.setdefault(guild.id, [])
        result: discord.ScheduledEvent | None = None
        try:
            result = next(_get_cached_event(events, value))
        except StopIteration:
            log.debug("%s is not yet cached for guild %d", value, guild.id)
        else:
            log.debug("%s is already cached for guild %d.", value, guild.id)
            return result

        match = _get_id_match(value)

        if match:
            # ID match
            event_id = int(match.group(1))
            result = guild.get_scheduled_event(event_id)
        else:
            pattern = (
                r"https?://(?:(ptb|canary|www)\.)?discord\.com/events/"
                r"(?P<guild_id>[0-9]{15,20})/"
                r"(?P<event_id>[0-9]{15,20})$"
            )
            match = re.match(pattern, value, flags=re.IGNORECASE)
            if match:
                # URL match
                guild = itx.client.get_guild(int(match.group("guild_id")))

                if guild is not None:
                    event_id = int(match.group("event_id"))
                    result = guild.get_scheduled_event(event_id)
            # lookup by name
            else:
                result = discord.utils.get(guild.scheduled_events, name=value)
        if result is None:
            raise app_commands.TransformerError(value, self.type, self) from None

        if not events:
            _guild_events_cache[itx.guild.id] = [result]
        else:
            _guild_events_cache[itx.guild.id].append(result)

        return result

    @property
    def type(self) -> AppCommandOptionType:
        return AppCommandOptionType.string
