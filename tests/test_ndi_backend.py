"""Native NDI FourCC mapping and rejected-frame cleanup."""

from fractions import Fraction
from types import SimpleNamespace

import numpy as np
import pytest

from quickreplay.input.ndi.backend import PyNdiReceiver
from quickreplay.input.ndi.errors import NdiUnsupportedFormatError


@pytest.fixture
def fake_ndi():
    freed = []
    ndi = SimpleNamespace(
        RECV_TIMESTAMP_UNDEFINED=-1,
        FOURCC_VIDEO_TYPE_UYVY=1,
        FOURCC_VIDEO_TYPE_BGRA=2,
        recv_free_video_v2=lambda receiver, frame: freed.append((receiver, frame)),
    )
    return ndi, freed


@pytest.mark.parametrize(("fourcc", "expected"), [(1, "UYVY"), (2, "BGRA")])
def test_native_video_fourcc_maps_to_raw_pixel_format(fake_ndi, fourcc, expected) -> None:
    ndi, freed = fake_ndi
    native = SimpleNamespace(
        timestamp=123,
        FourCC=fourcc,
        xres=2,
        yres=1,
        line_stride_in_bytes=8,
        frame_rate_N=60,
        frame_rate_D=1,
        data=np.zeros(8, dtype=np.uint8),
    )
    receiver = object()

    raw = PyNdiReceiver(receiver)._video(ndi, native)

    assert raw.pixel_format == expected
    assert raw.fps == Fraction(60, 1)
    assert raw.handle is native
    assert freed == []


def test_unsupported_native_video_is_freed_before_rejection(fake_ndi) -> None:
    ndi, freed = fake_ndi
    native = SimpleNamespace(timestamp=123, FourCC=99)
    receiver = object()

    with pytest.raises(NdiUnsupportedFormatError, match="supported: UYVY, BGRA"):
        PyNdiReceiver(receiver)._video(ndi, native)

    assert freed == [(receiver, native)]
