from __future__ import annotations

import math

from discord import Colour as DiscordColor

from . import _typings as t
from .bot import Interaction

MAX_PERCEIVED = 764.83
MAX_EUCLEDIAN = 441.67

# lower value = more similar
SIMILARITY_CUTOFF = 0.3

EPSILON = 1e-6


def hsl_to_rgb(hue: float, saturation: float, lightness: float) -> tuple[int, int, int]:
    """Convert to RGB from HSL.

    Args:
        hue (float): degrees [0, 360]
        saturation (float): percentage [0, 1]
        lightness (float): percentage [0, 1]

    Sources:
        - https://stackoverflow.com/a/44134328
        - https://en.wikipedia.org/wiki/HSL_and_HSV#HSL_to_RGB_alternative
    """

    a = saturation * min(lightness, 1 - lightness)
    h = hue / 30

    # n = offset for rgb components (r=0, g=8, b=4)
    def f(n: int) -> int:
        # hue shift
        # k is split into 12 different angles of 30deg intervals.
        # 0,4,8 are unique and evenly spaced angles for k.
        k = (n + h) % 12
        value = lightness - a * max(-1, min((k - 3, 9 - k, 1)))
        return round(255 * value)

    return f(0), f(8), f(4)


def squared_delta(x: tuple[int, int, int], y: tuple[int, int, int]) -> tuple[int, int, int]:
    dr = x[0] - y[0]
    dg = x[1] - y[1]
    db = x[2] - y[2]
    return dr * dr, dg * dg, db * db


def perceived_distance_between(x: tuple[int, int, int], y: tuple[int, int, int]) -> float:
    """Uses cmetric formula from `CompuPhase`:

    Note that `ΔR = R1 - R2`, similarly for green and blue components.

    Formula:
        `ΔC = √((2 + r̄/256) * ΔR² + 4 * ΔG² + (2 + (255 - r̄)/256) * ΔB²)`

    Sources:
        - https://www.compuphase.com/cmetric.htm
    """
    r_mean = (x[0] + y[0]) >> 1
    dr2, dg2, db2 = squared_delta(x, y)

    term_r = ((512 * r_mean) * dr2) >> 8
    term_g = 4 * dg2
    term_b = ((767 - r_mean) * db2) >> 8

    dist = math.sqrt(term_r + term_g + term_b)
    return dist / MAX_PERCEIVED


def euclidean_distance_between(x: tuple[int, int, int], y: tuple[int, int, int]) -> float:
    return (math.sqrt(sum(squared_delta(x, y)))) / MAX_EUCLEDIAN


def luminance(x: tuple[int, int, int]) -> float:
    r, g, b = x
    return (77 * r + 150 * g + 29 * b) >> 8


def is_similar_to(x: tuple[int, int, int], y: tuple[int, int, int]) -> bool:
    p = perceived_distance_between(x, y)
    e = euclidean_distance_between(x, y)

    lum_x = luminance(x)
    lum_y = luminance(y)
    lum_delta_norm = abs(lum_x - lum_y) * (1 / 255)

    score = p + 0.5 * e + 0.2 * lum_delta_norm

    return score <= SIMILARITY_CUTOFF + EPSILON


class Color(DiscordColor):
    @classmethod
    async def transform(cls: type[Color], itx: Interaction, value: str, /) -> Color:
        return t.cast("Color", cls.from_str(value))

    @classmethod
    def from_hsl(cls: type[Color], hue: float, saturation: float, lightness: float) -> Color:
        """Get color from HSL values

        Args:
            hue (float): degrees [0, 360]
            saturation (float): percentage [0, 1]
            lightness (float): percentage [0, 1]
        """
        return cls.from_rgb(*hsl_to_rgb(hue, saturation, lightness))

    @classmethod
    def white(cls: type[t.Self]) -> t.Self:
        return cls(0xF0F0F0)

    @classmethod
    def black(cls: type[t.Self]) -> t.Self:
        return cls.default()


__all__ = ("Color",)
