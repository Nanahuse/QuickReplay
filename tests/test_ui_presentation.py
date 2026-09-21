"""Pure presentation helpers."""

from fractions import Fraction

from quickreplay.app.state import ApplicationState
from quickreplay.input.models import (
    AudioStreamInfo,
    StreamInfo,
    VideoStreamInfo,
)
from quickreplay.recording.models import RecordingMetrics
from quickreplay.ui.presentation import (
    buffer_fraction,
    camera_backend_options,
    control_state,
    format_audio,
    format_buffer,
    format_duration_ns,
    format_fps,
    format_signed_duration_ns,
    format_signed_frames,
    format_stream_info,
    metrics_view,
    state_label,
)


def _stream_info(*, audio: AudioStreamInfo | None) -> StreamInfo:
    return StreamInfo(VideoStreamInfo(1920, 1080, Fraction(60, 1), "UYVY"), audio)


def _metrics() -> RecordingMetrics:
    return RecordingMetrics(
        captured_video_frames=100,
        recorded_video_frames=100,
        captured_audio_samples=0,
        recorded_audio_samples=0,
        video_queue_drops=1,
        audio_queue_drops=2,
        buffer_duration_ns=57_800_000_000,
        segment_count=29,
        input_fps=60.0,
        recording_fps=59.9,
    )


def test_format_fps() -> None:
    assert format_fps(Fraction(60, 1)) == "60"
    assert format_fps(Fraction(60000, 1001)) == "59.94"
    assert format_fps(Fraction(30000, 1001)) == "29.97"


def test_format_stream_info() -> None:
    assert format_stream_info(_stream_info(audio=None)) == "1920 × 1080 | 60 fps | UYVY"
    assert format_stream_info(None) == "—"


def test_format_audio() -> None:
    assert format_audio(_stream_info(audio=AudioStreamInfo(48000, 2))) == ("Audio: 48 kHz / Stereo")
    assert format_audio(_stream_info(audio=AudioStreamInfo(48000, 1))) == ("Audio: 48 kHz / Mono")
    assert format_audio(_stream_info(audio=None)) == "Audio: None"


def test_format_buffer_and_fraction() -> None:
    assert format_buffer(57_800_000_000, 120) == "57.8 / 120 s"
    assert buffer_fraction(60_000_000_000, 120) == 0.5
    assert buffer_fraction(240_000_000_000, 120) == 1.0
    assert buffer_fraction(-1, 120) == 0.0


def test_metrics_view() -> None:
    view = metrics_view(_metrics(), buffer_max_seconds=120)
    assert view is not None
    assert view.input_fps == "60.0"
    assert view.recording_fps == "59.9"
    assert view.buffer == "57.8 / 120 s"
    assert view.segments == "29"
    assert view.drops == "Video 1 / Audio 2"


def test_metrics_view_none() -> None:
    assert metrics_view(None, buffer_max_seconds=120) is None


def test_state_labels_cover_all_states() -> None:
    for state in ApplicationState:
        assert state_label(state)


def test_control_state() -> None:
    idle = control_state(ApplicationState.IDLE, has_selection=True, discovering=False)
    assert idle.start_enabled
    assert idle.input_enabled
    assert not idle.replay_enabled

    no_selection = control_state(ApplicationState.IDLE, has_selection=False, discovering=False)
    assert not no_selection.start_enabled

    recording = control_state(ApplicationState.RECORDING, has_selection=True, discovering=False)
    assert recording.replay_enabled
    assert not recording.start_enabled
    assert not recording.input_enabled

    replay = control_state(ApplicationState.REPLAY, has_selection=True, discovering=False)
    assert replay.resume_enabled
    assert not replay.replay_enabled

    preparing = control_state(
        ApplicationState.PREPARING_REPLAY, has_selection=True, discovering=False
    )
    assert not preparing.start_enabled
    assert not preparing.replay_enabled
    assert not preparing.resume_enabled

    error = control_state(ApplicationState.ERROR, has_selection=True, discovering=False)
    assert not error.start_enabled
    assert not error.input_enabled

    discovering = control_state(ApplicationState.IDLE, has_selection=True, discovering=True)
    assert not discovering.start_enabled
    assert not discovering.refresh_enabled


def test_camera_backend_options() -> None:
    assert camera_backend_options("win32") == ("any", "msmf", "dshow")
    assert camera_backend_options("linux") == ("any", "v4l2")
    assert camera_backend_options("darwin") == ("any",)


def test_format_duration_ns() -> None:
    assert format_duration_ns(0) == "00:00.000"
    assert format_duration_ns(1_000_000) == "00:00.001"
    assert format_duration_ns(1_000_000_000) == "00:01.000"
    assert format_duration_ns(61_234_000_000) == "01:01.234"
    assert format_duration_ns(3_723_456_000_000) == "1:02:03.456"


def test_format_signed_duration_ns() -> None:
    assert format_signed_duration_ns(750_000_000) == "+00:00.750"
    assert format_signed_duration_ns(-750_000_000) == "-00:00.750"
    assert format_signed_duration_ns(0) == "00:00.000"


def test_format_signed_frames() -> None:
    assert format_signed_frames(45) == "+45"
    assert format_signed_frames(-12) == "-12"
    assert format_signed_frames(0) == "0"
