"""Shim for typing- and annotation-related symbols to avoid runtime dependencies on `typing` or `typing-extensions`.

A warning for annotation-related symbols: Do not directly import them from this module
(e.g. `from ._typings import Any`)! Doing so will trigger the module-level `__getattr__`, causing `typing` to
get imported. Instead, import the module and use symbols via attribute access as needed
(e.g. `from . import _typings [as t]`). To avoid those symbols being evaluated at runtime, which would also cause
`typing` to get imported, make sure to put `from __future__ import annotations` at the top of the module.
"""

from __future__ import annotations

TYPE_CHECKING = False
if TYPE_CHECKING:
    from typing import (
        Annotated,
        Any,
        Concatenate,
        Literal,
        NamedTuple,
        Never,
        Protocol,
        Self,
        TypeVar,
        cast,
        override,
    )
else:

    def __getattr__(name: str):
        if name in {
            "Annotated",
            "Any",
            "Concatenate",
            "Literal",
            "Never",
            "Self",
            "NamedTuple",
            "Protocol",
            "override",
            "TypeVar",
            "cast",
        }:
            import typing

            return getattr(typing, name)

        msg = f"module {__name__!r} has no attribute {name!r}"
        raise AttributeError(msg)


__all__ = (
    "TYPE_CHECKING",
    "Annotated",
    "Any",
    "Concatenate",
    "Literal",
    "NamedTuple",
    "Never",
    "Protocol",
    "Self",
    "TypeVar",
    "cast",
    "override",
)
