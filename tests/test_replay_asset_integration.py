"""End-to-end pipeline: capture -> segments -> ring -> snapshot -> replay asset."""

from fractions import Fraction
from pathlib import Path

from quickreplay.recording.ring_storage import RingStorage
from quickreplay.replay.asset_builder import ReplayAssetBuilder
from quickreplay.replay.models import ReplaySnapshot

SECOND = 1_000_000_000
FPS = Fraction(60, 1)


def test_full_pipeline(tmp_path: Path, record_segments, replay_probe) -> None:
    segments, info = record_segments(
        tmp_path,
        duration_ns=4_500_000_000,
        fps=FPS,
        width=64,
        height=36,
        sample_rate=48000,
        channels=2,
    )
    ring = RingStorage(buffer_duration_ns=60 * SECOND)
    for segment in segments:
        ring.add(segment)

    output = tmp_path / "replay-session"
    with ring.snapshot() as lease:
        snapshot = ReplaySnapshot(segments=lease.segments, stream_info=info)
        asset = ReplayAssetBuilder().build(snapshot, output)
        assert lease.released is False

    assert lease.released is True
    assert asset.path == output / "replay.mkv"
    facts = replay_probe(asset.path)
    assert len(facts.decoded_video_pts) == sum(segment.video_frames for segment in segments)
    assert facts.decoded_audio_samples == sum(segment.audio_samples for segment in segments)
    assert asset.duration_ns == ring.duration_ns


def test_lease_pins_expired_segments_during_build(tmp_path: Path, record_segments) -> None:
    segments, info = record_segments(
        tmp_path,
        duration_ns=6 * SECOND,
        fps=FPS,
        width=64,
        height=36,
        sample_rate=48000,
        channels=2,
    )
    assert len(segments) >= 3
    first, second, third = segments[0], segments[1], segments[2]

    ring = RingStorage(buffer_duration_ns=4 * SECOND)
    ring.add(first)
    ring.add(second)

    lease = ring.snapshot()
    snapshot = ReplaySnapshot(segments=lease.segments, stream_info=info)

    # The third segment pushes the first out of the retention window, but the
    # lease keeps its file alive while the replay asset is built.
    ring.add(third)
    assert first.path.exists()
    assert second.path.exists()

    asset = ReplayAssetBuilder().build(snapshot, tmp_path / "out")
    assert asset.path.exists()
    assert first.path.exists()
    assert second.path.exists()

    # Once the asset is complete the segments are independent of it.
    lease.release()
    assert not first.path.exists()
    assert second.path.exists()
    assert third.path.exists()
