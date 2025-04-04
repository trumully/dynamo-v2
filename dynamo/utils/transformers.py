from __future__ import annotations

import re

from discord.app_commands import Transformer

_ID_REGEX = re.compile(r"([0-9]{15,20})$")


class DynamoTransformer(Transformer["Dynamo"]):  # type: ignore[reportUnknownVariable]
    """Base class for transformers that are used in the Dynamo library.

    This class is a subclass of `app_commands.Transformer` and provides a
    common interface for all transformers in the library. It also provides
    some utility methods for working with transformers.
    """

    @staticmethod
    def _get_id_match(value: str) -> re.Match[str] | None:
        return _ID_REGEX.match(value)

    @staticmethod
    def _get_cached[T](values: list[T], value: str, /) -> T:
        return NotImplemented
