"""Tests for RingStorage: add, retention, deletion, chronology and integration."""

from collections.abc import Callable
from fractions import Fraction
from pathlib import Path

import pytest

from quickreplay.input.models import VideoFrame
from quickreplay.recording.errors import (
    RingStorageError,
    SegmentDeleteError,
    SegmentOrderError,
)
from quickreplay.recording.models import Segment
from quickreplay.recording.ring_storage import RingStorage
from quickreplay.recording.segment_recorder import SegmentRecorder

SECOND = 1_000_000_000


def test_add_and_properties(make_segment: Callable[..., Segment]) -> None:
    ring = RingStorage(buffer_duration_ns=10 * SECOND)
    s0 = make_segment(0, 0, 2 * SECOND)
    s1 = make_segment(1, 2 * SECOND, 4 * SECOND)

    ring.add(s0)
    ring.add(s1)

    assert ring.segments == (s0, s1)
    assert ring.segment_count == 2
    assert ring.duration_ns == 4 * SECOND


def test_empty_ring_properties() -> None:
    ring = RingStorage(buffer_duration_ns=10 * SECOND)
    assert ring.segments == ()
    assert ring.segment_count == 0
    assert ring.duration_ns == 0


def test_retention_boundary_deletes_expired_file(make_segment: Callable[..., Segment]) -> None:
    ring = RingStorage(buffer_duration_ns=4 * SECOND)
    s0 = make_segment(0, 0, 2 * SECOND)
    s1 = make_segment(1, 2 * SECOND, 4 * SECOND)
    s2 = make_segment(2, 4 * SECOND, 6 * SECOND)

    ring.add(s0)
    ring.add(s1)
    ring.add(s2)

    # cutoff = 6s - 4s = 2s, and s0.end == cutoff -> expired.
    assert ring.segments == (s1, s2)
    assert not s0.path.exists()
    assert s1.path.exists()
    assert s2.path.exists()


def test_retention_keeps_whole_segments(make_segment: Callable[..., Segment]) -> None:
    ring = RingStorage(buffer_duration_ns=5 * SECOND)
    for index in range(3):
        ring.add(make_segment(index, index * 2 * SECOND, (index + 1) * 2 * SECOND))

    # cutoff = 1s: nothing expires, so the buffer may exceed the configured span.
    assert ring.segment_count == 3
    assert ring.duration_ns == 6 * SECOND


def test_retention_is_time_based_not_count_based(make_segment: Callable[..., Segment]) -> None:
    ring = RingStorage(buffer_duration_ns=2 * SECOND)
    s0 = make_segment(0, 0, 1 * SECOND)
    s1 = make_segment(1, 1 * SECOND, 5 * SECOND)
    s2 = make_segment(2, 5 * SECOND, 6 * SECOND)

    ring.add(s0)
    ring.add(s1)
    ring.add(s2)

    # cutoff = 6s - 2s = 4s: only s0 (end 1s) expires.
    assert ring.segments == (s1, s2)
    assert not s0.path.exists()


def test_chronology_rejects_overlap(make_segment: Callable[..., Segment]) -> None:
    ring = RingStorage(buffer_duration_ns=100 * SECOND)
    ring.add(make_segment(0, 0, 2 * SECOND))
    with pytest.raises(SegmentOrderError):
        ring.add(make_segment(1, 1 * SECOND, 3 * SECOND))


def test_chronology_rejects_gap(make_segment: Callable[..., Segment]) -> None:
    ring = RingStorage(buffer_duration_ns=100 * SECOND)
    ring.add(make_segment(0, 0, 2 * SECOND))
    with pytest.raises(SegmentOrderError):
        ring.add(make_segment(1, 3 * SECOND, 5 * SECOND))


def test_chronology_rejects_duplicate_and_backward_id(make_segment: Callable[..., Segment]) -> None:
    ring = RingStorage(buffer_duration_ns=100 * SECOND)
    ring.add(make_segment(5, 0, 2 * SECOND))
    with pytest.raises(SegmentOrderError):
        ring.add(make_segment(5, 2 * SECOND, 4 * SECOND))
    with pytest.raises(SegmentOrderError):
        ring.add(make_segment(4, 2 * SECOND, 4 * SECOND))


def test_add_missing_file_raises(tmp_path: Path) -> None:
    ring = RingStorage(buffer_duration_ns=4 * SECOND)
    missing = Segment(
        id=0,
        path=tmp_path / "missing.mkv",
        session_start_ns=0,
        session_end_ns=2 * SECOND,
        video_frames=1,
        audio_samples=0,
    )
    with pytest.raises(RingStorageError):
        ring.add(missing)


def test_clear_deletes_all_segments(make_segment: Callable[..., Segment]) -> None:
    ring = RingStorage(buffer_duration_ns=100 * SECOND)
    s0 = make_segment(0, 0, 2 * SECOND)
    s1 = make_segment(1, 2 * SECOND, 4 * SECOND)
    ring.add(s0)
    ring.add(s1)

    ring.clear()

    assert ring.segments == ()
    assert ring.duration_ns == 0
    assert not s0.path.exists()
    assert not s1.path.exists()


def test_delete_failure_is_not_silent_and_keeps_entry(
    make_segment: Callable[..., Segment],
) -> None:
    def delete(_path: Path) -> None:
        raise OSError("injected delete failure")

    ring = RingStorage(buffer_duration_ns=4 * SECOND, delete_file=delete)
    s0 = make_segment(0, 0, 2 * SECOND)
    s1 = make_segment(1, 2 * SECOND, 4 * SECOND)
    s2 = make_segment(2, 4 * SECOND, 6 * SECOND)
    ring.add(s0)
    ring.add(s1)

    with pytest.raises(SegmentDeleteError) as excinfo:
        ring.add(s2)  # s0 expires but cannot be deleted

    assert s0.path in excinfo.value.paths

    # The new segment is registered and the failed entry is not lost.
    assert ring.segments == (s1, s2)
    assert s0.path.exists()
    # The failure is retryable through a later add.
    assert ring.segment_count == 2


def test_delete_retry_succeeds_on_later_operation(
    make_segment: Callable[..., Segment],
) -> None:
    state = {"fail": True}

    def delete(path: Path) -> None:
        if state["fail"]:
            state["fail"] = False
            raise OSError("injected first failure")
        path.unlink()

    ring = RingStorage(buffer_duration_ns=4 * SECOND, delete_file=delete)
    s0 = make_segment(0, 0, 2 * SECOND)
    s1 = make_segment(1, 2 * SECOND, 4 * SECOND)
    s2 = make_segment(2, 4 * SECOND, 6 * SECOND)
    ring.add(s0)
    ring.add(s1)

    with pytest.raises(SegmentDeleteError):
        ring.add(s2)
    assert s0.path.exists()

    # A later add retries the pending deletion and now succeeds.
    ring.add(make_segment(3, 6 * SECOND, 8 * SECOND))
    assert not s0.path.exists()


def test_externally_deleted_file_is_treated_as_success(
    make_segment: Callable[..., Segment],
) -> None:
    ring = RingStorage(buffer_duration_ns=4 * SECOND)
    s0 = make_segment(0, 0, 2 * SECOND)
    s1 = make_segment(1, 2 * SECOND, 4 * SECOND)
    s2 = make_segment(2, 4 * SECOND, 6 * SECOND)
    ring.add(s0)
    ring.add(s1)

    s0.path.unlink()  # external deletion

    ring.add(s2)  # retention treats FileNotFoundError as a successful cleanup

    assert ring.segments == (s1, s2)


def test_segment_recorder_integration(media, tmp_path: Path) -> None:
    fps = Fraction(60, 1)
    info = media.stream_info(fps=fps, width=64, height=36)
    recorder = SegmentRecorder()
    recorder.start(media.session(tmp_path, info))
    frames = media.frames(duration_ns=6_500_000_000, fps=fps, width=64, height=36)
    segments: list[Segment] = []
    for frame in frames:
        if isinstance(frame, VideoFrame):
            segments.extend(recorder.push_video(frame))
        else:
            recorder.push_audio(frame)
    last = recorder.finish()
    if last is not None:
        segments.append(last)
    recorder.close()

    assert len(segments) >= 3
    assert all(segment.path.exists() for segment in segments)

    ring = RingStorage(buffer_duration_ns=4 * SECOND)
    for segment in segments:
        ring.add(segment)

    newest_end_ns = segments[-1].session_end_ns
    cutoff_ns = newest_end_ns - 4 * SECOND
    for segment in segments:
        if segment.session_end_ns <= cutoff_ns:
            assert not segment.path.exists()
        else:
            assert segment.path.exists()
            assert segment in ring.segments
