"""Tests for input configuration, stream info and frame models."""

from fractions import Fraction

import pytest

from quickreplay.input.models import (
    AudioFrame,
    AudioStreamInfo,
    NdiInputConfig,
    VideoStreamInfo,
)


def test_ndi_input_config() -> None:
    config = NdiInputConfig(source_name="PC-A (OBS)")
    assert config.source_name == "PC-A (OBS)"
    with pytest.raises(ValueError):
        NdiInputConfig(source_name="")


def test_fps_is_fraction_not_float() -> None:
    info = VideoStreamInfo(width=1920, height=1080, fps=Fraction(60000, 1001), pixel_format="UYVY")
    assert isinstance(info.fps, Fraction)
    assert info.fps == Fraction(60000, 1001)
    assert info.fps.numerator == 60000
    assert info.fps.denominator == 1001


@pytest.mark.parametrize("width,height", [(0, 1080), (1920, 0), (-1, 1080)])
def test_video_stream_info_validation(width: int, height: int) -> None:
    with pytest.raises(ValueError):
        VideoStreamInfo(width=width, height=height, fps=Fraction(60, 1), pixel_format="UYVY")


@pytest.mark.parametrize("sample_rate,channels", [(0, 2), (48000, 0)])
def test_audio_stream_info_validation(sample_rate: int, channels: int) -> None:
    with pytest.raises(ValueError):
        AudioStreamInfo(sample_rate=sample_rate, channels=channels)


def test_audio_frame_rejects_negative_sample_count() -> None:
    with pytest.raises(ValueError):
        AudioFrame(timestamp_ns=0, sample_rate=48000, channels=2, sample_count=-1, data=object())
