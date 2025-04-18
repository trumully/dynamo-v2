from __future__ import annotations

import msgspec
from base2048 import decode, encode

from dynamo import _typing_shim as t

encoder = msgspec.json.Encoder()
decoder = msgspec.json.Decoder()


def to_json(obj: t.Any) -> str:
    return encoder.encode(obj).decode("utf-8")


def b2048pack(o: object, /) -> str:
    return encode(msgspec.msgpack.encode(o))


def b2048unpack[T](packed: str, type_: type[T], /) -> T:
    return msgspec.msgpack.decode(decode(packed), type=type_)
