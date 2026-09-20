"""Fake camera backend for tests.

It implements the :class:`~quickreplay.input.camera.backend.CameraBackend`
protocol with plain Python objects, so discovery, mode requests, capture,
read failures and release can be exercised in CI without a physical camera or
an OpenCV capture runtime.
"""

import itertools
from collections.abc import Callable
from fractions import Fraction
from typing import Any

import numpy as np

from quickreplay.input.camera.backend import CameraProperty
from quickreplay.units import NANOSECONDS_PER_SECOND, round_fraction


class FakeCapture:
    """A scripted ``cv2.VideoCapture``."""

    def __init__(
        self,
        *,
        opened: bool = True,
        frames: list[Any] | None = None,
        properties: dict[CameraProperty, float] | None = None,
        set_results: dict[CameraProperty, bool] | None = None,
    ) -> None:
        self._opened = opened
        self._frames = list(frames or [])
        self._properties = dict(properties or {})
        self._set_results = dict(set_results or {})
        self.set_calls: list[tuple[CameraProperty, float]] = []
        self.release_count = 0

    def is_opened(self) -> bool:
        return self._opened

    def set(self, prop: CameraProperty, value: float) -> bool:
        self.set_calls.append((prop, value))
        result = self._set_results.get(prop, True)
        if result:
            self._properties[prop] = value
        return result

    def get(self, prop: CameraProperty) -> float:
        return self._properties.get(prop, 0.0)

    def read(self) -> tuple[bool, np.ndarray | None]:
        if not self._frames:
            return False, None
        item = self._frames.pop(0)
        if isinstance(item, BaseException):
            raise item
        if item is None:
            return False, None
        return True, item

    def release(self) -> None:
        self.release_count += 1


class FakeCameraBackend:
    """A :class:`CameraBackend` that uses a factory function."""

    def __init__(self, factory: Callable[[int, int], FakeCapture]) -> None:
        self._factory = factory
        self.captures: list[FakeCapture] = []

    def open_capture(self, device_index: int, api_preference: int) -> FakeCapture:
        capture = self._factory(device_index, api_preference)
        self.captures.append(capture)
        return capture


def bgr_frame(width: int, height: int, value: int = 0) -> np.ndarray:
    return np.full((height, width, 3), value, dtype=np.uint8)


def frame_clock(*, fps: Fraction, start_ns: int = 1_000_000_000) -> Callable[[], int]:
    """A monotonic clock returning ``start_ns + i / fps`` on the i-th call."""
    counter = itertools.count()

    def clock() -> int:
        index = next(counter)
        return start_ns + round_fraction(Fraction(index * NANOSECONDS_PER_SECOND, 1) / fps)

    return clock
