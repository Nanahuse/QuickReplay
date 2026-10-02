"""Shared unit constants and exact (non-float) rounding helpers.

All internal time in Version 2 is expressed as integer nanoseconds and all
frame rates as :class:`fractions.Fraction`.  These helpers keep conversions
exact; float is never used as the source of truth.
"""

import math
from fractions import Fraction

NANOSECONDS_PER_SECOND = 1_000_000_000
"""Number of nanoseconds in one second."""


def round_fraction(value: Fraction) -> int:
    """Round a :class:`~fractions.Fraction` to the nearest int.

    Ties are rounded away from zero.  Rounding is explicit so that timestamp to
    frame conversion is deterministic and independently testable.
    """
    if value >= 0:
        return math.floor(value + Fraction(1, 2))
    return -math.floor(-value + Fraction(1, 2))
