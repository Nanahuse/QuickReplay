"""Tests for input configuration, stream info and frame models."""

from fractions import Fraction

import pytest

from quickreplay.input.models import (
    AudioFrame,
    AudioStreamInfo,
    CameraInputConfig,
    CameraMode,
    NdiInputConfig,
    VideoStreamInfo,
)


def test_ndi_input_config() -> None:
    config = NdiInputConfig(source_name="PC-A (OBS)")
    assert config.source_name == "PC-A (OBS)"
    with pytest.raises(ValueError):
        NdiInputConfig(source_name="")


def test_camera_input_config() -> None:
    mode = CameraMode(width=1920, height=1080, fps=Fraction(60, 1))
    config = CameraInputConfig(device_name="USB Camera", device_index=0, backend="msmf", mode=mode)
    assert config.mode is mode
    assert config.device_index == 0

    without_mode = CameraInputConfig(device_name="Cam", device_index=1, backend="dshow")
    assert without_mode.mode is None
    with pytest.raises(ValueError):
        CameraInputConfig(device_name="Cam", device_index=-1, backend="dshow")


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
