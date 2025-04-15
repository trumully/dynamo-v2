import re
from collections.abc import Sequence
from enum import StrEnum, auto
from pathlib import Path
from warnings import deprecated

from dynamo import _typings as t

from .files import ROOT

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


def is_cjk(text: str) -> CJK:
    """Check if a string contains any CJK characters."""
    if re.search(r"[\u4e00-\u9fff\u3400-\u4dbf]", text):
        return CJK.CHINESE

    if re.search(r"[\u3040-\u309f\u30a0-\u30ff]", text):
        return CJK.JAPANESE

    if re.search(r"[\uac00-\ud7af\u1100-\u11ff]", text):
        return CJK.KOREAN

    return CJK.NONE


class Font(t.NamedTuple):
    regular: Path
    bold: Path


def _get_font(name: str) -> Font:
    regular = FONT_PATH / f"{name}-Regular.ttf"
    bold = FONT_PATH / f"{name}-Bold.ttf"
    return Font(regular, bold)


FONTS = {
    CJK.NONE: _get_font("NotoSans"),
    CJK.CHINESE: _get_font("NotoSansTC"),
    CJK.JAPANESE: _get_font("NotoSansJP"),
    CJK.KOREAN: _get_font("NotoSansKR"),
}
