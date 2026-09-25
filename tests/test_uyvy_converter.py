"""UYVY support in the recording FrameConverter."""

from fractions import Fraction

import numpy as np
import pytest

from quickreplay.input.models import VideoFrame
from quickreplay.recording.errors import SegmentFormatError
from quickreplay.recording.frame_converter import FrameConverter


def _uyvy_frame(width: int, height: int, value: int = 128) -> VideoFrame:
    data = np.full((height, width * 2), value, dtype=np.uint8)
    return VideoFrame(0, width, height, Fraction(60, 1), "UYVY", data)


def test_uyvy_converts_to_yuv420p() -> None:
    frame = _uyvy_frame(160, 90, value=128)

    av_frame = FrameConverter().to_av_video(frame)

    assert av_frame.format.name == "yuv420p"
    assert av_frame.width == 160
    assert av_frame.height == 90


def test_uyvy_odd_width_is_supported() -> None:
    frame = _uyvy_frame(158, 90)

    av_frame = FrameConverter().to_av_video(frame)

    assert av_frame.width == 158
    assert av_frame.format.name == "yuv420p"


def test_uyvy_wrong_shape_is_rejected() -> None:
    bad = VideoFrame(0, 4, 2, Fraction(60, 1), "UYVY", np.zeros((2, 4), dtype=np.uint8))

    with pytest.raises(SegmentFormatError):
        FrameConverter().to_av_video(bad)


def test_existing_pixel_formats_still_work() -> None:
    converter = FrameConverter()
    rgb = VideoFrame(0, 4, 2, Fraction(60, 1), "RGB24", np.zeros((2, 4, 3), dtype=np.uint8))

    av_frame = converter.to_av_video(rgb)

    assert av_frame.format.name == "yuv420p"
    assert (av_frame.width, av_frame.height) == (4, 2)


def test_bgra_converts_to_yuv420p() -> None:
    frame = VideoFrame(
        0,
        4,
        2,
        Fraction(60, 1),
        "BGRA",
        np.zeros((2, 4, 4), dtype=np.uint8),
    )

    av_frame = FrameConverter().to_av_video(frame)

    assert av_frame.format.name == "yuv420p"
    assert (av_frame.width, av_frame.height) == (4, 2)
