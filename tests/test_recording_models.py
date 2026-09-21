"""Tests for recording domain models."""

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from quickreplay.recording.models import (
    RecordingMetrics,
    Segment,
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
