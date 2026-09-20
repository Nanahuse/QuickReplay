"""Thin backend around OpenCV ``VideoCapture``.

This module is the only place that touches OpenCV native types.  The rest of
the package depends on :class:`CameraBackend` / :class:`CameraCapture` and on
:class:`CameraProperty`, so a fake backend can exercise every code path without
a physical camera or a capture runtime (see ``tests/fake_camera.py``).

``cv2`` itself is imported lazily, so importing the core package never loads
OpenCV and never fails on a machine without a camera.
"""

import math
import time
from enum import StrEnum
from fractions import Fraction
from typing import Any, Protocol

import numpy as np

from quickreplay.input.camera.errors import CameraBackendError, CameraFormatError

DEFAULT_CLOCK_NS = time.perf_counter_ns
"""Monotonic clock used for camera frame timestamps."""

_CANONICAL_FPS: tuple[Fraction, ...] = (
    Fraction(60, 1),
    Fraction(60000, 1001),
    Fraction(50, 1),
    Fraction(30000, 1001),
    Fraction(30, 1),
    Fraction(24000, 1001),
    Fraction(25, 1),
    Fraction(24, 1),
    Fraction(15, 1),
    Fraction(10, 1),
)
"""Broadcast rates camera backends commonly report as rounded floats."""

_FPS_TOLERANCE = 0.05
"""Distance within which a reported float FPS is snapped to a canonical rate."""

_FPS_DENOMINATOR_LIMIT = 1000
"""Denominator limit for FPS values that do not match a canonical rate."""


class CameraProperty(StrEnum):
    """Camera properties requested or read through the backend."""

    FRAME_WIDTH = "frame_width"
    FRAME_HEIGHT = "frame_height"
    FPS = "fps"


_PROPERTY_NAMES: dict[CameraProperty, str] = {
    CameraProperty.FRAME_WIDTH: "CAP_PROP_FRAME_WIDTH",
    CameraProperty.FRAME_HEIGHT: "CAP_PROP_FRAME_HEIGHT",
    CameraProperty.FPS: "CAP_PROP_FPS",
}

_BACKEND_NAMES: dict[str, str] = {
    "any": "CAP_ANY",
    "msmf": "CAP_MSMF",
    "dshow": "CAP_DSHOW",
    "v4l2": "CAP_V4L2",
}


def import_cv2() -> Any:
    """Import and return the ``cv2`` module, or raise if unavailable."""
    try:
        import cv2  # noqa: PLC0415 - deliberately lazy
    except Exception as exc:  # noqa: BLE001 - ImportError / OSError / DLL errors
        raise CameraBackendError(f"OpenCV is not available: {exc}") from exc
    return cv2


def cv2_available() -> bool:
    """Whether OpenCV can be imported on this machine."""
    try:
        import_cv2()
    except CameraBackendError:
        return False
    return True


def resolve_backend_code(name: str) -> int:
    """Map a backend name to its OpenCV ``CAP_*`` constant.

    Unknown names are rejected instead of silently falling back to ``CAP_ANY``.
    """
    cv2 = import_cv2()
    key = name.strip().lower()
    attribute = _BACKEND_NAMES.get(key)
    if attribute is None:
        raise CameraBackendError(
            f"unknown camera backend {name!r}; supported: {sorted(_BACKEND_NAMES)}"
        )
    return int(getattr(cv2, attribute))


def camera_fps_to_fraction(value: float) -> Fraction:
    """Convert a rounded float FPS report into an exact :class:`Fraction`.

    Values close to a canonical broadcast rate are snapped to it
    (``59.94 -> 60000/1001``); otherwise the value is rationalised with a
    bounded denominator.  Non-finite or non-positive values raise
    :class:`CameraFormatError`.
    """
    if not math.isfinite(value) or value <= 0:
        raise CameraFormatError(f"invalid camera FPS {value!r}")
    best = min(_CANONICAL_FPS, key=lambda rate: abs(value - float(rate)))
    if abs(value - float(best)) <= _FPS_TOLERANCE:
        return best
    return Fraction(value).limit_denominator(_FPS_DENOMINATOR_LIMIT)


class CameraCapture(Protocol):
    """One OpenCV capture device."""

    def is_opened(self) -> bool: ...

    def set(self, prop: CameraProperty, value: float) -> bool: ...

    def get(self, prop: CameraProperty) -> float: ...

    def read(self) -> tuple[bool, np.ndarray | None]: ...

    def release(self) -> None: ...


class CameraBackend(Protocol):
    """Create OpenCV capture devices."""

    def open_capture(self, device_index: int, api_preference: int) -> CameraCapture: ...


class OpenCvCameraBackend:
    """The real backend, backed by OpenCV."""

    def open_capture(self, device_index: int, api_preference: int) -> CameraCapture:
        cv2 = import_cv2()
        return OpenCvCapture(cv2.VideoCapture(device_index, api_preference))


class OpenCvCapture:
    """Wraps one ``cv2.VideoCapture`` without leaking it to the core."""

    def __init__(self, capture: Any) -> None:
        self._capture = capture

    def is_opened(self) -> bool:
        return bool(self._capture.isOpened())

    def set(self, prop: CameraProperty, value: float) -> bool:
        cv2 = import_cv2()
        code = getattr(cv2, _PROPERTY_NAMES[prop])
        return bool(self._capture.set(code, float(value)))

    def get(self, prop: CameraProperty) -> float:
        cv2 = import_cv2()
        code = getattr(cv2, _PROPERTY_NAMES[prop])
        return float(self._capture.get(code))

    def read(self) -> tuple[bool, np.ndarray | None]:
        ok, frame = self._capture.read()
        if frame is None:
            return bool(ok), None
        return bool(ok), frame

    def release(self) -> None:
        self._capture.release()
