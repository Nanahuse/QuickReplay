"""Replay domain models and exact frame-difference math."""

from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

from quickreplay.input.models import StreamInfo
from quickreplay.recording.models import Segment
from quickreplay.units import NANOSECONDS_PER_SECOND, round_fraction


@dataclass(frozen=True, slots=True)
class ReplaySnapshot:
    """Immutable set of segments frozen from the ring buffer for replay."""

    segments: tuple[Segment, ...]
    stream_info: StreamInfo


@dataclass(frozen=True, slots=True)
class ReplayAsset:
    """A completed, single-file, stream-copied replay asset (for example replay.mkv)."""

    path: Path
    duration_ns: int
    fps: Fraction

    def __post_init__(self) -> None:
        if self.duration_ns < 0:
            raise ValueError(f"duration_ns must not be negative, got {self.duration_ns}")
        if self.fps <= 0:
            raise ValueError(f"fps must be positive, got {self.fps}")


@dataclass(frozen=True, slots=True)
class SetPoint:
    """A replay set point, identified only by its timeline position."""

    position_ns: int


def frame_difference(
    current_position_ns: int,
    origin_position_ns: int,
    fps: Fraction,
) -> int:
    """Number of frames between two replay positions, computed without floats.

    ``diff_ns`` is converted to a :class:`~fractions.Fraction` of seconds,
    multiplied by *fps* and rounded to the nearest frame.
    """
    diff_ns = current_position_ns - origin_position_ns
    return round_fraction(Fraction(diff_ns, NANOSECONDS_PER_SECOND) * fps)
