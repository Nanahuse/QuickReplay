"""Camera backend name mapping and FPS rationalisation."""

import math
from fractions import Fraction

import cv2
import pytest

from quickreplay.input.camera.backend import camera_fps_to_fraction, resolve_backend_code
from quickreplay.input.camera.errors import CameraBackendError, CameraFormatError


@pytest.mark.parametrize(
    ("name", "constant"),
    [
        ("any", "CAP_ANY"),
        ("msmf", "CAP_MSMF"),
        ("dshow", "CAP_DSHOW"),
        ("v4l2", "CAP_V4L2"),
    ],
)
def test_backend_names_map_to_opencv_constants(name: str, constant: str) -> None:
    assert resolve_backend_code(name) == int(getattr(cv2, constant))


def test_backend_name_is_case_insensitive() -> None:
    assert resolve_backend_code("  MSMF ") == int(cv2.CAP_MSMF)


def test_unknown_backend_is_rejected() -> None:
    with pytest.raises(CameraBackendError):
        resolve_backend_code("bogus")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (60.0, Fraction(60, 1)),
        (30.0, Fraction(30, 1)),
        (25.0, Fraction(25, 1)),
        (60000 / 1001, Fraction(60000, 1001)),
        (30000 / 1001, Fraction(30000, 1001)),
        (24000 / 1001, Fraction(24000, 1001)),
    ],
)
def test_fps_rationalisation(value: float, expected: Fraction) -> None:
    assert camera_fps_to_fraction(value) == expected


@pytest.mark.parametrize("value", [0.0, -1.0, -60.0, math.nan, math.inf, -math.inf])
def test_invalid_fps_is_rejected(value: float) -> None:
    with pytest.raises(CameraFormatError):
        camera_fps_to_fraction(value)
