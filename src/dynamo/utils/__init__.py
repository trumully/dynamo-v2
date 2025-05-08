from __future__ import annotations

from pathlib import Path

from base2048 import decode, encode
from msgspec import json, msgpack
from platformdirs import PlatformDirs

from dynamo import _typing as t

dirs: PlatformDirs = PlatformDirs("dynamo", "trumully", roaming=False)


def resolve_path_with_links(path: Path, folder: bool = False) -> Path:
    try:
        return path.resolve(strict=True)
    except FileNotFoundError:
        path = resolve_path_with_links(path.parent, folder=True) / path.name
        if folder:
            # python default = read/write/traversable (0o777)
            path.mkdir(mode=0o700)
        else:
            # python default = read/writable (0o666)
            path.touch(mode=0o600)
        return path.resolve(strict=True)


ROOT = resolve_path_with_links(Path(__file__).parent.parent.parent.parent, folder=True)


encoder: json.Encoder = json.Encoder()


def to_json(obj: t.Any) -> str:
    return encoder.encode(obj).decode("utf-8")


def b2048pack(o: object, /) -> str:
    return encode(msgpack.encode(o))


def b2048unpack[T](packed: str, type_: type[T], /) -> T:
    return msgpack.decode(decode(packed), type=type_)
