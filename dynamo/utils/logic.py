from __future__ import annotations

from base2048 import decode, encode
from msgspec import json, msgpack

from dynamo import _typing_shim as t

encoder = json.Encoder()


def to_json(obj: t.Any) -> str:
    return encoder.encode(obj).decode("utf-8")


def b2048pack(o: object, /) -> str:
    return encode(msgpack.encode(o))


def b2048unpack[T](packed: str, type_: type[T], /) -> T:
    return msgpack.decode(decode(packed), type=type_)
