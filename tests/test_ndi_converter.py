"""Raw NDI frame conversion: copy-before-free, stride and payload contracts."""

from fractions import Fraction

import numpy as np
import pytest
from fake_ndi import fake_audio, fake_video

from quickreplay.input.ndi.backend import ndi_timestamp_to_ns
from quickreplay.input.ndi.converter import to_audio_frame, to_video_frame
from quickreplay.input.ndi.errors import NdiUnsupportedFormatError


def _payload(frame) -> np.ndarray:
    data = frame.data
    assert isinstance(data, np.ndarray)
    return data


def test_timestamp_conversion_is_integer_100ns() -> None:
    assert ndi_timestamp_to_ns(12_345_678) == 1_234_567_800
    assert ndi_timestamp_to_ns(0) == 0


@pytest.mark.parametrize("fps", [Fraction(60, 1), Fraction(60000, 1001)])
def test_fps_is_exact_fraction(fps: Fraction) -> None:
    frame = to_video_frame(fake_video(width=4, height=2, fps=fps))

    assert frame.fps == fps
    assert isinstance(frame.fps, Fraction)


def test_video_copy_before_free() -> None:
    raw = fake_video(width=4, height=2)
    original = raw.data.copy()

    frame = to_video_frame(raw)
    raw.data[:] = 200  # mutate the native buffer after conversion

    payload = _payload(frame)
    assert frame.pixel_format == "UYVY"
    assert payload.shape == (2, 8)
    assert payload.dtype == np.uint8
    assert np.array_equal(payload, original)
    assert not np.shares_memory(payload, raw.data)


def test_video_stride_padding_is_removed() -> None:
    width, height = 4, 3
    stride = width * 2 + 6
    native = np.arange(height * stride, dtype=np.uint8).reshape(height, stride)
    raw = fake_video(width=width, height=height, stride=stride, data=native)

    frame = to_video_frame(raw)
    payload = _payload(frame)

    assert payload.shape == (height, width * 2)
    assert np.array_equal(payload, native[:, : width * 2])
    assert not np.array_equal(payload, native)


def test_audio_copy_before_free_and_stereo_shape() -> None:
    raw = fake_audio(channels=2, samples=1600)
    raw.data[:] = 0.5
    original = raw.data.copy()

    frame = to_audio_frame(raw)
    raw.data[:] = -0.25  # mutate the native buffer after conversion

    payload = _payload(frame)
    assert payload.shape == (2, 1600)
    assert payload.dtype == np.float32
    assert np.array_equal(payload, original)
    assert not np.shares_memory(payload, raw.data)
    assert frame.sample_count == 1600
    assert frame.channels == 2
    assert frame.sample_rate == 48000


def test_audio_mono_is_supported() -> None:
    frame = to_audio_frame(fake_audio(channels=1, samples=100))

    assert _payload(frame).shape == (1, 100)
    assert frame.channels == 1


def test_audio_unsupported_channel_count() -> None:
    with pytest.raises(NdiUnsupportedFormatError):
        to_audio_frame(fake_audio(channels=3, samples=100))


def test_bgra_frame_is_copied_without_padding() -> None:
    width, height = 2, 2
    native = np.arange(height * width * 4, dtype=np.uint8).reshape(height, width * 4)
    raw = fake_video(width=width, height=height, pixel_format="BGRA", data=native)

    frame = to_video_frame(raw)

    assert frame.pixel_format == "BGRA"
    payload = _payload(frame)
    assert payload.shape == (height, width, 4)
    assert payload.dtype == np.uint8
    assert np.array_equal(payload, native.reshape(height, width, 4))
    assert payload.flags.c_contiguous
    assert not np.shares_memory(payload, native)


def test_bgra_padding_is_removed_and_payload_is_owned() -> None:
    width, height, stride = 2, 2, 12
    native = np.arange(height * stride, dtype=np.uint8).reshape(height, stride)
    raw = fake_video(width=width, height=height, stride=stride, data=native, pixel_format="BGRA")
    expected = native[:, : width * 4].copy()

    frame = to_video_frame(raw)
    native[:] = 255

    payload = _payload(frame)
    assert payload.shape == (height, width, 4)
    assert np.array_equal(payload.reshape(height, width * 4), expected)
    assert not np.shares_memory(payload, native)


def test_bgra_3d_pixels_are_copied_into_owned_contiguous_array() -> None:
    width, height = 3, 2
    native = np.arange(height * width * 4, dtype=np.uint8).reshape(height, width, 4)
    original = native.copy()
    raw = fake_video(
        width=width,
        height=height,
        stride=width * 4,
        pixel_format="BGRA",
        data=native,
    )

    frame = to_video_frame(raw)
    native[:] = 255

    payload = _payload(frame)
    assert frame.pixel_format == "BGRA"
    assert payload.shape == (height, width, 4)
    assert payload.dtype == np.uint8
    assert payload.flags.c_contiguous
    assert np.array_equal(payload, original)
    assert not np.shares_memory(payload, native)


def test_bgra_3d_non_contiguous_view_is_normalized() -> None:
    width, height = 3, 2
    base = np.arange(height * (width + 2) * 4, dtype=np.uint8).reshape(height, width + 2, 4)
    view = base[:, :width, :]
    raw = fake_video(
        width=width,
        height=height,
        stride=width * 4,
        pixel_format="BGRA",
        data=view,
    )

    payload = _payload(to_video_frame(raw))

    assert np.array_equal(payload, view)
    assert payload.flags.c_contiguous
    assert not np.shares_memory(payload, base)


@pytest.mark.parametrize(
    "data",
    [
        np.zeros((1, 3, 4), dtype=np.uint8),
        np.zeros((2, 2, 4), dtype=np.uint8),
        np.zeros((2, 3, 3), dtype=np.uint8),
        np.zeros((2, 3, 5), dtype=np.uint8),
        np.zeros((2, 3, 4), dtype=np.uint16),
    ],
)
def test_malformed_bgra_3d_shape_or_dtype_is_rejected(data: np.ndarray) -> None:
    raw = fake_video(
        width=3,
        height=2,
        stride=12,
        pixel_format="BGRA",
        data=data,
    )

    with pytest.raises(NdiUnsupportedFormatError):
        to_video_frame(raw)


@pytest.mark.parametrize(
    ("width", "height", "stride", "data"),
    [
        (2, 2, 8, np.zeros((1, 8), dtype=np.uint8)),
        (2, 2, 7, np.zeros((2, 8), dtype=np.uint8)),
        (2, 2, 8, np.zeros(15, dtype=np.uint8)),
        (2, 2, 8, np.asarray(1, dtype=np.uint8)),
    ],
)
def test_malformed_bgra_frames_are_rejected(
    width: int, height: int, stride: int, data: np.ndarray
) -> None:
    raw = fake_video(width=width, height=height, stride=stride, data=data, pixel_format="BGRA")

    with pytest.raises(NdiUnsupportedFormatError):
        to_video_frame(raw)


def test_unsupported_video_format_rejected() -> None:
    with pytest.raises(NdiUnsupportedFormatError):
        to_video_frame(fake_video(pixel_format="P216"))


def test_unsupported_audio_format_rejected() -> None:
    with pytest.raises(NdiUnsupportedFormatError):
        to_audio_frame(fake_audio(audio_format="S16"))
