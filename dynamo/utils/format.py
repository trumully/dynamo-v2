from collections.abc import Sequence
from enum import StrEnum, auto
from pathlib import Path
from warnings import deprecated

from dynamo import _typings as t

from .files import ROOT, resolve_path_with_links

FONT_PATH = ROOT / "assets" / "fonts"


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


class CJK(StrEnum):
    CHINESE = auto()
    JAPANESE = auto()
    KOREAN = auto()
    NONE = auto()


# https://en.wikipedia.org/wiki/Unicode_block
# KR
HANGUL = range(0xAC00, 0xD7AF + 1)
HANGUL_JAMO = range(0x1100, 0x11FF + 1)

# JP
HIRAGANA = range(0x3040, 0x309F + 1)
KATAKANA = range(0x30A0, 0x30FF + 1)

# Han
CJK_COMPAT = range(0xF900, 0xFAFF + 1)


def any_chars_in_ranges(text: str, *ranges: range) -> bool:
    return any(ord(c) in r for r in ranges for c in text)


def is_cjk(text: str) -> CJK:
    """Check if a string contains any CJK characters."""
    if any_chars_in_ranges(text, CJK_COMPAT):
        return CJK.CHINESE

    if any_chars_in_ranges(text, HIRAGANA, KATAKANA):
        return CJK.JAPANESE

    if any_chars_in_ranges(text, HANGUL, HANGUL_JAMO):
        return CJK.KOREAN

    return CJK.NONE


class Font(t.NamedTuple):
    regular: Path
    bold: Path


def _get_font(name: str) -> Font:
    regular = resolve_path_with_links(FONT_PATH / f"{name}-Regular.woff2")
    bold = resolve_path_with_links(FONT_PATH / f"{name}-Bold.woff2")
    return Font(regular, bold)


FONTS = {
    CJK.NONE: _get_font("NotoSans"),
    CJK.CHINESE: _get_font("NotoSansTC"),
    CJK.JAPANESE: _get_font("NotoSansJP"),
    CJK.KOREAN: _get_font("NotoSansKR"),
}
