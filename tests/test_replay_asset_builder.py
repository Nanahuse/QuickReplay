"""ReplayAssetBuilder validation, atomic finalize and failure cleanup."""

from dataclasses import replace
from fractions import Fraction
from pathlib import Path

import pytest

from quickreplay.recording.models import Segment
from quickreplay.replay.asset_builder import (
    REPLAY_FILENAME,
    REPLAY_TMP_FILENAME,
    ReplayAssetBuilder,
)
from quickreplay.replay.errors import (
    EmptyReplaySnapshotError,
    ReplayRemuxError,
    ReplaySegmentError,
    ReplayStreamMismatchError,
)
from quickreplay.replay.models import ReplaySnapshot

SECOND = 1_000_000_000
FPS = Fraction(60, 1)


def _snapshot(segments: tuple[Segment, ...], info) -> ReplaySnapshot:
    return ReplaySnapshot(segments=segments, stream_info=info)


def _shift(segment: Segment, *, segment_id: int, start_ns: int) -> Segment:
    return replace(
        segment,
        id=segment_id,
        session_start_ns=start_ns,
        session_end_ns=start_ns + segment.duration_ns,
    )


def test_empty_snapshot_rejected(media, tmp_path: Path) -> None:
    info = media.stream_info(fps=FPS, width=64, height=36)
    output = tmp_path / "out"

    with pytest.raises(EmptyReplaySnapshotError):
        ReplayAssetBuilder().build(_snapshot((), info), output)

    assert not output.exists()


def test_missing_segment_rejected(media, tmp_path: Path, make_segment) -> None:
    info = media.stream_info(fps=FPS, width=64, height=36)
    first = make_segment(0, 0, 2 * SECOND)
    second = make_segment(1, 2 * SECOND, 4 * SECOND)
    second.path.unlink()
    output = tmp_path / "out"

    with pytest.raises(ReplaySegmentError):
        ReplayAssetBuilder().build(_snapshot((first, second), info), output)

    assert not (output / REPLAY_FILENAME).exists()
    assert not (output / REPLAY_TMP_FILENAME).exists()


def test_chronology_gap_rejected(media, tmp_path: Path, make_segment) -> None:
    info = media.stream_info(fps=FPS, width=64, height=36)
    first = make_segment(0, 0, 2 * SECOND)
    second = make_segment(1, 3 * SECOND, 5 * SECOND)

    with pytest.raises(ReplaySegmentError):
        ReplayAssetBuilder().build(_snapshot((first, second), info), tmp_path / "out")


def test_chronology_overlap_rejected(media, tmp_path: Path, make_segment) -> None:
    info = media.stream_info(fps=FPS, width=64, height=36)
    first = make_segment(0, 0, 2 * SECOND)
    second = make_segment(1, SECOND, 3 * SECOND)

    with pytest.raises(ReplaySegmentError):
        ReplayAssetBuilder().build(_snapshot((first, second), info), tmp_path / "out")


def test_non_increasing_id_rejected(media, tmp_path: Path, make_segment) -> None:
    info = media.stream_info(fps=FPS, width=64, height=36)
    first = make_segment(1, 0, 2 * SECOND)
    second = make_segment(0, 2 * SECOND, 4 * SECOND)

    with pytest.raises(ReplaySegmentError):
        ReplayAssetBuilder().build(_snapshot((first, second), info), tmp_path / "out")


def test_stream_resolution_mismatch_rejected(media, tmp_path: Path, record_segments) -> None:
    first_dir = tmp_path / "a"
    second_dir = tmp_path / "b"
    first_dir.mkdir()
    second_dir.mkdir()
    first_segments, info = record_segments(
        first_dir, duration_ns=SECOND, fps=FPS, width=64, height=36
    )
    second_segments, _ = record_segments(
        second_dir, duration_ns=SECOND, fps=FPS, width=128, height=72
    )
    first = first_segments[0]
    second = _shift(second_segments[0], segment_id=1, start_ns=first.session_end_ns)
    output = tmp_path / "out"

    with pytest.raises(ReplayStreamMismatchError):
        ReplayAssetBuilder().build(_snapshot((first, second), info), output)

    assert not (output / REPLAY_FILENAME).exists()
    assert not (output / REPLAY_TMP_FILENAME).exists()


def test_stream_audio_presence_mismatch_rejected(media, tmp_path: Path, record_segments) -> None:
    first_dir = tmp_path / "a"
    second_dir = tmp_path / "b"
    first_dir.mkdir()
    second_dir.mkdir()
    first_segments, info = record_segments(
        first_dir, duration_ns=SECOND, fps=FPS, width=64, height=36, sample_rate=48000, channels=2
    )
    second_segments, _ = record_segments(
        second_dir, duration_ns=SECOND, fps=FPS, width=64, height=36
    )
    first = first_segments[0]
    second = _shift(second_segments[0], segment_id=1, start_ns=first.session_end_ns)

    with pytest.raises(ReplayStreamMismatchError):
        ReplayAssetBuilder().build(_snapshot((first, second), info), tmp_path / "out")


def test_success_publishes_atomically(media, tmp_path: Path, record_segments) -> None:
    segments, info = record_segments(
        tmp_path, duration_ns=SECOND, fps=FPS, width=64, height=36, sample_rate=48000, channels=2
    )
    output = tmp_path / "out"

    asset = ReplayAssetBuilder().build(_snapshot(segments, info), output)

    assert asset.path == output / REPLAY_FILENAME
    assert asset.path.exists()
    assert not (output / REPLAY_TMP_FILENAME).exists()
    assert asset.duration_ns == segments[-1].session_end_ns - segments[0].session_start_ns


def test_success_replaces_existing_asset(media, tmp_path: Path, record_segments) -> None:
    segments, info = record_segments(
        tmp_path, duration_ns=SECOND, fps=FPS, width=64, height=36, sample_rate=48000, channels=2
    )
    output = tmp_path / "out"
    output.mkdir()
    (output / REPLAY_FILENAME).write_bytes(b"stale")

    asset = ReplayAssetBuilder().build(_snapshot(segments, info), output)

    assert asset.path.read_bytes() != b"stale"
    assert not (output / REPLAY_TMP_FILENAME).exists()


def test_failure_cleans_up_partial_output(media, tmp_path: Path, record_segments) -> None:
    segments, info = record_segments(
        tmp_path, duration_ns=SECOND, fps=FPS, width=64, height=36, sample_rate=48000, channels=2
    )
    output = tmp_path / "out"

    def failing_remux(segments, tmp_path):
        Path(tmp_path).write_bytes(b"partial")
        raise ReplayRemuxError("injected failure")

    with pytest.raises(ReplayRemuxError):
        ReplayAssetBuilder(remux=failing_remux).build(_snapshot(segments, info), output)

    assert not (output / REPLAY_TMP_FILENAME).exists()
    assert not (output / REPLAY_FILENAME).exists()
    for segment in segments:
        assert segment.path.exists()


def test_failure_preserves_existing_asset(media, tmp_path: Path, record_segments) -> None:
    segments, info = record_segments(
        tmp_path, duration_ns=SECOND, fps=FPS, width=64, height=36, sample_rate=48000, channels=2
    )
    output = tmp_path / "out"
    output.mkdir()
    (output / REPLAY_FILENAME).write_bytes(b"completed")

    def failing_remux(segments, tmp_path):
        raise ReplayRemuxError("injected failure")

    with pytest.raises(ReplayRemuxError):
        ReplayAssetBuilder(remux=failing_remux).build(_snapshot(segments, info), output)

    assert (output / REPLAY_FILENAME).read_bytes() == b"completed"
    assert not (output / REPLAY_TMP_FILENAME).exists()


def test_source_segments_are_not_modified(media, tmp_path: Path, record_segments) -> None:
    segments, info = record_segments(
        tmp_path,
        duration_ns=4_500_000_000,
        fps=FPS,
        width=64,
        height=36,
        sample_rate=48000,
        channels=2,
    )
    before = {segment.path: segment.path.read_bytes() for segment in segments}

    ReplayAssetBuilder().build(_snapshot(segments, info), tmp_path / "out")

    for segment in segments:
        assert segment.path.read_bytes() == before[segment.path]


def test_asset_fps_is_exact_fraction(media, tmp_path: Path, record_segments) -> None:
    fps = Fraction(60000, 1001)
    segments, info = record_segments(
        tmp_path,
        duration_ns=4_500_000_000,
        fps=fps,
        width=64,
        height=36,
        sample_rate=48000,
        channels=2,
    )

    asset = ReplayAssetBuilder().build(_snapshot(segments, info), tmp_path / "out")

    assert asset.fps == fps
    assert isinstance(asset.fps, Fraction)
