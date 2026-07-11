import aiohttp
from async_utils.task_cache import lrutaskcache

from . import _typings as t
from .logs import Logger, get_logger

type JSON_ro = t.Mapping[str, JSON_ro] | t.Sequence[JSON_ro] | str | int | float | bool | None


log: Logger = get_logger(__name__)


def url_cache_transform(
    args: tuple[aiohttp.ClientSession, str], kwargs: t.Mapping[str, object]
) -> tuple[tuple[str], t.Mapping[str, object]]:
    _client, url = args
    return (url,), kwargs


@lrutaskcache(cache_transform=url_cache_transform)
async def get_cached_bytes(session: aiohttp.ClientSession, url: str, /) -> bytes:
    try:
        async with session.get(url) as r:
            r.raise_for_status()
            return await r.read()
    except aiohttp.ClientResponseError as ex:
        log.exception("%s\n%d: %s", url, ex.code, ex.message)
        raise
    except Exception:
        log.exception("Unexptected error ocurred for %s", url, stack_info=True)
        raise


@lrutaskcache(cache_transform=url_cache_transform)
async def get_cached_json(session: aiohttp.ClientSession, url: str, /) -> JSON_ro:
    try:
        async with session.get(url) as r:
            r.raise_for_status()
            return await r.json()
    except aiohttp.ClientResponseError as ex:
        log.exception("%s\n%d: %s", url, ex.code, ex.message)
        raise
    except Exception:
        log.exception("Unexptected error ocurred for %s", url, stack_info=True)
        raise


class MusicPresenceExtra(t.TypedDict):
    discord_application_id: str


class MusicPresencePlayer(t.TypedDict):
    id: str
    name: str
    extra: MusicPresenceExtra


class MusicPresencePlayerResponse(t.TypedDict):
    players: t.Sequence[MusicPresencePlayer]


class MusicPresenceService:
    _session: aiohttp.ClientSession
    _base_url: str

    def __init__(self, session: aiohttp.ClientSession) -> None:
        self._session = session
        self._base_url = "https://live.musicpresence.app/v3"

    def _get_mp_url(self, url: str) -> str:
        _mp_external, _, proper_url = url.partition("https/")
        return f"https://{proper_url}" if proper_url else url

    async def get_players(self) -> MusicPresencePlayerResponse:
        url = self._base_url + "/players.min.json"
        return t.cast("MusicPresencePlayerResponse", await get_cached_json(self._session, url))

    async def get_icon(self, player: str) -> bytes:
        player_normalised = player.strip().replace(" ", "-").lower()
        url = self._base_url + f"/icons/{player_normalised}/logo-128.png"
        return await get_cached_bytes(self._session, url)


class Services:
    music_presence: MusicPresenceService

    def __init__(self, session: aiohttp.ClientSession) -> None:
        self.music_presence = MusicPresenceService(session)
