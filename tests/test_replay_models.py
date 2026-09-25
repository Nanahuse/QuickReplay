"""Tests for replay domain models and frame-difference math."""

from dataclasses import FrozenInstanceError
from fractions import Fraction
from pathlib import Path

import pytest

from quickreplay.input.models import AudioStreamInfo, StreamInfo, VideoStreamInfo
from quickreplay.recording.models import Segment
from quickreplay.replay.models import ReplayAsset, ReplaySnapshot, SetPoint, frame_difference


def _segment(segment_id: int, start_ns: int, end_ns: int) -> Segment:
    return Segment(
        id=segment_id,
        path=Path(f"segment_{segment_id:06d}.mkv"),
        session_start_ns=start_ns,
        session_end_ns=end_ns,
        video_frames=120,
        audio_samples=96000,
    )


def _stream_info() -> StreamInfo:
    return StreamInfo(
        video=VideoStreamInfo(1920, 1080, Fraction(60, 1), "UYVY"),
        audio=AudioStreamInfo(48000, 2),
    )


def test_replay_snapshot_holds_tuple_of_segments() -> None:
    segments = (_segment(0, 0, 2_000_000_000), _segment(1, 2_000_000_000, 4_000_000_000))
    snapshot = ReplaySnapshot(segments=segments, stream_info=_stream_info())
    assert isinstance(snapshot.segments, tuple)
    assert len(snapshot.segments) == 2
    assert snapshot.stream_info.video.fps == Fraction(60, 1)


def test_replay_snapshot_is_immutable() -> None:
    snapshot = ReplaySnapshot(segments=(), stream_info=_stream_info())
    attribute = "segments"
    with pytest.raises(FrozenInstanceError):
        setattr(snapshot, attribute, ())


def test_replay_asset() -> None:
    asset = ReplayAsset(path=Path("replay.mkv"), duration_ns=30_000_000_000, fps=Fraction(60, 1))
    assert asset.path == Path("replay.mkv")
    assert asset.duration_ns == 30_000_000_000
    with pytest.raises(ValueError):
        ReplayAsset(path=Path("replay.mkv"), duration_ns=-1, fps=Fraction(60, 1))


def test_set_point_holds_only_position() -> None:
    point = SetPoint(position_ns=1_950_000_000)
    assert point.position_ns == 1_950_000_000


def test_frame_difference_60fps() -> None:
    origin_ns = 1_950_000_000
    current_ns = 2_050_000_000
    assert frame_difference(current_ns, origin_ns, Fraction(60, 1)) == 6


def test_frame_difference_5994fps() -> None:
    # 20 frames at 60000/1001 fps is 20 * 1001/60000 s = 333666.66... us.
    fps = Fraction(60000, 1001)
    origin_ns = 0
    current_ns = round(20 * 1001 / 60000 * 1_000_000_000)
    assert frame_difference(current_ns, origin_ns, fps) == 20


def test_frame_difference_is_symmetric() -> None:
    fps = Fraction(60, 1)
    assert frame_difference(0, 2_050_000_000, fps) == -123


def test_frame_difference_ties_away_from_zero() -> None:
    half_frame_ns = 250_000_000
    assert frame_difference(half_frame_ns, 0, Fraction(2, 1)) == 1
    assert frame_difference(-half_frame_ns, 0, Fraction(2, 1)) == -1
