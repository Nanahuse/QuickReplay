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


def test_unsupported_video_format_rejected() -> None:
    with pytest.raises(NdiUnsupportedFormatError):
        to_video_frame(fake_video(pixel_format="BGRA"))


def test_unsupported_audio_format_rejected() -> None:
    with pytest.raises(NdiUnsupportedFormatError):
        to_audio_frame(fake_audio(audio_format="S16"))
