"""Media-level verification of the stream-copy replay remux."""

import math
from fractions import Fraction
from pathlib import Path

import av

from quickreplay.recording.models import Segment
from quickreplay.replay.asset_builder import ReplayAssetBuilder
from quickreplay.replay.models import ReplaySnapshot
from quickreplay.replay.remux import probe_layout, validate_segment_layouts
from quickreplay.units import round_fraction

FPS_60 = Fraction(60, 1)
FPS_5994 = Fraction(60000, 1001)


def _snapshot(record_segments, directory: Path, **kwargs):
    segments, info = record_segments(directory, **kwargs)
    return ReplaySnapshot(segments=segments, stream_info=info), segments, info


def _boundary_ms(segments: tuple[Segment, ...]) -> set[int]:
    return {round_fraction(Fraction(segment.session_start_ns, 1_000_000)) for segment in segments}


def _decoded_frames(segment: Segment) -> int:
    """Decoded video frame count of a single segment file."""
    with av.open(str(segment.path)) as container:
        return sum(1 for _ in container.decode(container.streams.video[0]))


def test_remux_60fps(tmp_path: Path, record_segments, replay_probe) -> None:
    snapshot, segments, _info = _snapshot(
        record_segments,
        tmp_path,
        duration_ns=4_500_000_000,
        fps=FPS_60,
        width=64,
        height=36,
        sample_rate=48000,
        channels=2,
    )
    asset = ReplayAssetBuilder().build(snapshot, tmp_path / "out")
    facts = replay_probe(asset.path)

    assert asset.fps == FPS_60
    assert facts.video_codec == "h264"
    assert facts.audio_codec == "pcm_f32le"
    assert len(facts.decoded_video_pts) == sum(segment.video_frames for segment in segments)
    assert facts.decoded_audio_samples == sum(segment.audio_samples for segment in segments)
    assert asset.duration_ns == segments[-1].session_end_ns - segments[0].session_start_ns


def test_remux_5994fps(tmp_path: Path, record_segments, replay_probe) -> None:
    snapshot, segments, _info = _snapshot(
        record_segments,
        tmp_path,
        duration_ns=4_500_000_000,
        fps=FPS_5994,
        width=64,
        height=36,
        sample_rate=48000,
        channels=2,
    )
    asset = ReplayAssetBuilder().build(snapshot, tmp_path / "out")
    facts = replay_probe(asset.path)

    assert asset.fps == FPS_5994
    assert len(facts.decoded_video_pts) == sum(segment.video_frames for segment in segments)
    assert facts.decoded_audio_samples == sum(segment.audio_samples for segment in segments)


def test_remux_video_and_audio_streams(
    tmp_path: Path, record_segments, replay_probe, probe
) -> None:
    snapshot, segments, _info = _snapshot(
        record_segments,
        tmp_path,
        duration_ns=4_500_000_000,
        fps=FPS_60,
        width=64,
        height=36,
        sample_rate=48000,
        channels=2,
    )
    asset = ReplayAssetBuilder().build(snapshot, tmp_path / "out")
    facts = replay_probe(asset.path)
    source = probe(segments[0].path)

    assert facts.audio_codec is not None
    assert facts.audio_sample_rate == source.audio_sample_rate
    assert facts.audio_channels == source.audio_channels
    assert facts.video_codec == source.video_codec
    assert facts.video_codec == "h264"
    assert facts.audio_codec == "pcm_f32le"


def test_remux_video_only(tmp_path: Path, record_segments, replay_probe) -> None:
    snapshot, segments, _info = _snapshot(
        record_segments,
        tmp_path,
        duration_ns=4_500_000_000,
        fps=FPS_60,
        width=64,
        height=36,
    )
    asset = ReplayAssetBuilder().build(snapshot, tmp_path / "out")
    facts = replay_probe(asset.path)

    assert facts.audio_codec is None
    assert facts.decoded_audio_samples == 0
    assert facts.audio_packet_pts == ()
    assert len(facts.decoded_video_pts) == sum(segment.video_frames for segment in segments)


def test_frame_count_matches_segments(tmp_path: Path, record_segments, replay_probe) -> None:
    snapshot, segments, _info = _snapshot(
        record_segments,
        tmp_path,
        duration_ns=6_500_000_000,
        fps=FPS_5994,
        width=64,
        height=36,
        sample_rate=48000,
        channels=2,
    )
    asset = ReplayAssetBuilder().build(snapshot, tmp_path / "out")
    facts = replay_probe(asset.path)

    per_segment = [_decoded_frames(segment) for segment in segments]
    assert len(facts.decoded_video_pts) == sum(per_segment)
    assert facts.decoded_audio_samples == sum(segment.audio_samples for segment in segments)


def test_packet_timestamps_are_monotonic(tmp_path: Path, record_segments, replay_probe) -> None:
    snapshot, _segments, _info = _snapshot(
        record_segments,
        tmp_path,
        duration_ns=4_500_000_000,
        fps=FPS_60,
        width=64,
        height=36,
        sample_rate=48000,
        channels=2,
    )
    asset = ReplayAssetBuilder().build(snapshot, tmp_path / "out")
    facts = replay_probe(asset.path)

    assert facts.video_packet_dts[0] == 0
    assert facts.video_packet_pts[0] == 0
    assert all(
        b > a for a, b in zip(facts.video_packet_dts, facts.video_packet_dts[1:], strict=False)
    )
    assert all(
        b > a for a, b in zip(facts.video_packet_pts, facts.video_packet_pts[1:], strict=False)
    )
    assert facts.audio_packet_dts[0] == 0
    assert all(
        b >= a for a, b in zip(facts.audio_packet_dts, facts.audio_packet_dts[1:], strict=False)
    )
    assert all(
        b >= a for a, b in zip(facts.audio_packet_pts, facts.audio_packet_pts[1:], strict=False)
    )


def test_boundary_continuity(tmp_path: Path, record_segments, replay_probe) -> None:
    snapshot, segments, _info = _snapshot(
        record_segments,
        tmp_path,
        duration_ns=4_500_000_000,
        fps=FPS_60,
        width=64,
        height=36,
        sample_rate=48000,
        channels=2,
    )
    asset = ReplayAssetBuilder().build(snapshot, tmp_path / "out")
    facts = replay_probe(asset.path)
    pts = facts.decoded_video_pts

    nominal_ms = Fraction(1000, 1) / FPS_60
    low = math.floor(nominal_ms)
    high = math.ceil(nominal_ms)
    deltas = [b - a for a, b in zip(pts, pts[1:], strict=False)]
    assert deltas
    assert all(low <= delta <= high for delta in deltas)

    boundaries = _boundary_ms(segments)
    assert boundaries <= set(pts)


def test_keyframes_survive_at_segment_boundaries(
    tmp_path: Path, record_segments, replay_probe
) -> None:
    snapshot, segments, _info = _snapshot(
        record_segments,
        tmp_path,
        duration_ns=4_500_000_000,
        fps=FPS_60,
        width=64,
        height=36,
        sample_rate=48000,
        channels=2,
    )
    asset = ReplayAssetBuilder().build(snapshot, tmp_path / "out")
    facts = replay_probe(asset.path)

    assert facts.keyframe_pts[0] == 0
    assert _boundary_ms(segments) <= set(facts.keyframe_pts)


def test_seek_into_later_segment(tmp_path: Path, record_segments) -> None:
    snapshot, segments, _info = _snapshot(
        record_segments,
        tmp_path,
        duration_ns=6_500_000_000,
        fps=FPS_60,
        width=64,
        height=36,
        sample_rate=48000,
        channels=2,
    )
    asset = ReplayAssetBuilder().build(snapshot, tmp_path / "out")

    target_ns = segments[2].session_start_ns + 100_000_000
    target_ms = round_fraction(Fraction(target_ns, 1_000_000))
    with av.open(str(asset.path)) as container:
        container.seek(target_ms, backward=True, stream=container.streams.video[0])
        decoded = [
            frame.pts
            for frame in container.decode(container.streams.video[0])
            if frame.pts is not None
        ]

    assert decoded
    assert decoded[0] <= target_ms
    assert decoded[-1] >= target_ms


def test_single_segment(tmp_path: Path, record_segments, replay_probe) -> None:
    snapshot, segments, _info = _snapshot(
        record_segments,
        tmp_path,
        duration_ns=1_000_000_000,
        fps=FPS_60,
        width=64,
        height=36,
        sample_rate=48000,
        channels=2,
    )
    assert len(segments) == 1
    asset = ReplayAssetBuilder().build(snapshot, tmp_path / "out")
    facts = replay_probe(asset.path)

    assert asset.path.exists()
    assert len(facts.decoded_video_pts) == segments[0].video_frames
    assert facts.decoded_audio_samples == segments[0].audio_samples


def test_probe_layout_and_validation(tmp_path: Path, record_segments) -> None:
    segments, _info = record_segments(
        tmp_path, duration_ns=4_500_000_000, fps=FPS_60, width=64, height=36
    )

    layout = probe_layout(segments[0].path)
    assert layout.video.codec == "h264"
    assert layout.video.width == 64
    assert layout.video.height == 36
    assert layout.audio is None
    validate_segment_layouts(segments)
