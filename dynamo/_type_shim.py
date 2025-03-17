"""Shim for typing- and annotation-related symbols to avoid runtime dependencies on `typing` or `typing-extensions`."""

from __future__ import annotations

TYPE_CHECKING = False
if TYPE_CHECKING:
    from typing import (
        Any,
        Concatenate,
        Literal,
        NamedTuple,
        Never,
        Protocol,
        Self,
        TypeVar,
        cast,
    )
else:

    def __getattr__(name: str):
        if name in {
            "Any",
            "Concatenate",
            "Literal",
            "Never",
            "Self",
            "NamedTuple",
            "Protocol",
            "TypeVar",
            "cast",
        }:
            import typing

            return getattr(typing, name)

        msg = f"module {__name__!r} has no attribute {name!r}"
        raise AttributeError(msg)


__all__ = (
    "TYPE_CHECKING",
    "Any",
    "Concatenate",
    "Literal",
    "NamedTuple",
    "Never",
    "Protocol",
    "Self",
    "TypeVar",
    "cast",
)
