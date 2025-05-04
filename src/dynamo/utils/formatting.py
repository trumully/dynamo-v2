from __future__ import annotations

from collections.abc import Sequence
from warnings import deprecated

from dynamo import _typing_shim as t


# Uses PEP 702 to allow *only* Sequence[str]
@t.overload
@deprecated("seq must not be a string")
def human_join(seq: str, /, *, delimiter: str = ", ", end: str = "and") -> str: ...


@t.overload
def human_join(  # noqa: F811
    seq: Sequence[str], /, *, delimiter: str = ", ", end: str = "and"
) -> str: ...


def human_join(seq: Sequence[str], /, *, delimiter: str = ", ", end: str = "and") -> str:  # noqa: F811
    if (size := len(seq)) == 0:
        return ""

    if size == 1:
        return seq[0]

    if size == 2:
        return f"{seq[0]} {end} {seq[1]}"

    return delimiter.join(seq[:-1]) + f" {end} {seq[-1]}"
