"""Tests for recording domain models."""

from dataclasses import FrozenInstanceError
from fractions import Fraction
from pathlib import Path
from uuid import uuid4

import pytest

from quickreplay.input.models import AudioStreamInfo, StreamInfo, VideoStreamInfo
from quickreplay.recording.models import (
    RecordingMetrics,
    RecordingSession,
    Segment,
    WorkerErrorCode,
    WorkerState,
)


def _segment() -> Segment:
    return Segment(
        id=1,
        path=Path("segment_000001.mkv"),
        session_start_ns=2_000_000_000,
        session_end_ns=4_000_000_000,
        video_frames=120,
        audio_samples=96000,
    )


def test_segment_fields_and_duration() -> None:
    segment = _segment()
    assert segment.id == 1
    assert segment.path == Path("segment_000001.mkv")
    assert segment.duration_ns == 2_000_000_000
    assert segment.video_frames == 120
    assert segment.audio_samples == 96000


def test_segment_is_immutable() -> None:
    segment = _segment()
    attribute = "video_frames"
    with pytest.raises(FrozenInstanceError):
        setattr(segment, attribute, 121)


def test_segment_rejects_invalid_values() -> None:
    with pytest.raises(ValueError):
        Segment(
            id=0,
            path=Path("x.mkv"),
            session_start_ns=2_000_000_000,
            session_end_ns=1_000_000_000,
            video_frames=0,
            audio_samples=0,
        )
    with pytest.raises(ValueError):
        Segment(
            id=0,
            path=Path("x.mkv"),
            session_start_ns=0,
            session_end_ns=1,
            video_frames=-1,
            audio_samples=0,
        )


def test_recording_session() -> None:
    session = RecordingSession(
        id=uuid4(),
        stream_info=StreamInfo(
            video=VideoStreamInfo(1920, 1080, Fraction(60, 1), "UYVY"),
            audio=AudioStreamInfo(48000, 2),
        ),
        epoch_ns=123,
        directory=Path("buffer/session"),
    )
    assert session.epoch_ns == 123
    assert session.directory == Path("buffer/session")


def test_recording_metrics() -> None:
    metrics = RecordingMetrics(
        captured_video_frames=120,
        recorded_video_frames=120,
        captured_audio_samples=96000,
        recorded_audio_samples=96000,
        video_queue_drops=0,
        audio_queue_drops=0,
        buffer_duration_ns=30_000_000_000,
        segment_count=15,
        input_fps=59.94,
        recording_fps=60.0,
    )
    assert metrics.input_fps == pytest.approx(59.94)
    with pytest.raises(ValueError):
        RecordingMetrics(
            captured_video_frames=-1,
            recorded_video_frames=0,
            captured_audio_samples=0,
            recorded_audio_samples=0,
            video_queue_drops=0,
            audio_queue_drops=0,
            buffer_duration_ns=0,
            segment_count=0,
            input_fps=0.0,
            recording_fps=0.0,
        )


def test_worker_state_preserves_required_distinctions() -> None:
    names = {state.name for state in WorkerState}
    assert {"RECORDING", "FREEZING", "FROZEN", "ERROR", "SHUTTING_DOWN"} <= names


def test_worker_error_codes() -> None:
    for code in ("INPUT_NOT_FOUND", "ENCODER_FAILED", "REPLAY_ASSET_FAILED", "DISK_FULL"):
        assert code in {member.name for member in WorkerErrorCode}
