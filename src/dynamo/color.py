from __future__ import annotations

import math
from collections.abc import Generator

from discord import Colour as DiscordColor

from . import _typing as t
from .bot import Interaction

MAX_PERCEIVED = 764.83
MAX_EUCLEDIAN = 441.67

# lower value = more similar
SIMILARITY_CUTOFF = 0.3

EPSILON = 1e-6


class Color(DiscordColor):
    def perceived_distance_from(self, other: Color) -> float:
        """Uses cmetric formula from `CompuPhase`_:

        Note that `ΔR = R1 - R2`, similarly for green and blue components.

        Formula:
            `ΔC = √((2 + r̄/256) * ΔR² + 4 * ΔG² + (2 + (255 - r̄)/256) * ΔB²)`

        .. _CompuPhase:
            https://www.compuphase.com/cmetric.htm
        """
        r_mean = (self.r + other.r) >> 1
        r, g, b = self.squared_delta(other)
        dist = math.sqrt((((512 * r_mean) * r) >> 8) + 4 * g + (((767 - r_mean) * b) >> 8))
        return dist / MAX_PERCEIVED

    def squared_delta(self, other: Color) -> Generator[int]:
        delta_r = self.r - other.r
        delta_g = self.g - other.g
        delta_b = self.b - other.b
        return (int(math.pow(x, 2)) for x in (delta_r, delta_g, delta_b))

    def euclidean_distance_from(self, other: Color) -> float:
        return (math.sqrt(sum(self.squared_delta(other)))) / MAX_EUCLEDIAN

    def is_similar_to(self, other: Color) -> bool:
        p_dist = self.perceived_distance_from(other)
        e_dist = self.euclidean_distance_from(other)
        x = self.r + self.g + self.b
        y = other.r + other.g + other.b

        thresh = SIMILARITY_CUTOFF * (1 + abs((x / MAX_PERCEIVED) - (y / MAX_PERCEIVED)))

        return p_dist <= (thresh + EPSILON) and e_dist <= (thresh + EPSILON)

    @classmethod
    async def transform(cls: type[t.Self], itx: Interaction, value: str, /) -> t.Self:
        return t.cast("t.Self", cls.from_str(value))

    @classmethod
    def from_hsl(cls: type[t.Self], hue: float, sat: float, lum: float) -> t.Self:
        # Adapted from https://stackoverflow.com/a/44134328
        # and https://en.wikipedia.org/wiki/HSL_and_HSV#HSL_to_RGB_alternative
        lum /= 100
        a = sat * min(lum, 1 - lum) / 100

        # n = offset for rgb components (r=0, g=8, b=4)
        def f(n: int):
            # hue shift
            # k is split into 12 different angles of 30deg intervals.
            # 0,4,8 are unique and evenly spaced angles for k.
            k = (n + hue / 30) % 12

            color = lum - a * max(min((k - 3, 9 - k, 1)), -1)
            return round(255 * color)

        return cls.from_rgb(f(0), f(8), f(4))

    @classmethod
    def white(cls: type[t.Self]) -> t.Self:
        return cls(0xF0F0F0)

    @classmethod
    def black(cls: type[t.Self]) -> t.Self:
        return cls.default()


__all__: tuple[str, ...] = ("Color",)
