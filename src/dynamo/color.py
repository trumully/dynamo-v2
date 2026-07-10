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


def hsl_to_rgb(hue: float, saturation: float, lightness: float) -> Color:
    c = (1 - abs(2 * lightness - 1)) * saturation
    x = c * (1 - abs((hue / 60) % 2 - 1))
    m = lightness - c / 2

    if hue < 60:
        r, g, b = c, x, 0
    elif hue < 120:
        r, g, b = x, c, 0
    elif hue < 180:
        r, g, b = 0, c, x
    elif hue < 240:
        r, g, b = 0, x, c
    elif hue < 300:
        r, g, b = x, 0, c
    else:
        r, g, b = c, 0, x

    return Color.from_rgb(round((r + m) * 255), round((g + m) * 255), round((b + m) * 255))


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


def saturation(c: tuple[int, int, int]) -> float:
    return max(c) - min(c)


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


__all__ = ("Color",)
