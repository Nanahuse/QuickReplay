"""Media-level verification: decode, keyframes, PTS and stream layout."""

from collections.abc import Iterable
from dataclasses import replace
from fractions import Fraction
from pathlib import Path

import pytest

from quickreplay.input.models import AudioFrame, VideoFrame
from quickreplay.recording.models import Segment
from quickreplay.recording.segment_recorder import SegmentRecorder


def _record(media, recorder: SegmentRecorder, **kwargs) -> list[Segment]:
    frames: Iterable[VideoFrame | AudioFrame] = media.frames(**kwargs)
    segments: list[Segment] = []
    for frame in frames:
        if isinstance(frame, VideoFrame):
            segments.extend(recorder.push_video(frame))
        else:
            recorder.push_audio(frame)
    last = recorder.finish()
    if last is not None:
        segments.append(last)
    return segments


def test_media_60fps(media, tmp_path: Path, probe) -> None:
    fps = Fraction(60, 1)
    info = media.stream_info(fps=fps, width=64, height=36, sample_rate=48000, channels=2)
    recorder = SegmentRecorder()
    recorder.start(media.session(tmp_path, info))
    segments = _record(
        media,
        recorder,
        duration_ns=4_500_000_000,
        fps=fps,
        width=64,
        height=36,
        sample_rate=48000,
        channels=2,
    )
    recorder.close()

    assert len(segments) == 3
    for segment in segments:
        facts = probe(segment.path)
        assert facts.first_video_pts == 0
        assert facts.keyframe_count >= 1
        assert facts.decoded_video_frames == segment.video_frames
        assert facts.video_rate == fps
        assert facts.audio_present
        assert facts.first_audio_pts == 0
        assert facts.audio_samples == segment.audio_samples


def test_media_5994fps(media, tmp_path: Path, probe) -> None:
    fps = Fraction(60000, 1001)
    info = media.stream_info(fps=fps, width=64, height=36, sample_rate=48000, channels=2)
    recorder = SegmentRecorder()
    recorder.start(media.session(tmp_path, info))
    segments = _record(
        media,
        recorder,
        duration_ns=4_500_000_000,
        fps=fps,
        width=64,
        height=36,
        sample_rate=48000,
        channels=2,
    )
    recorder.close()

    assert len(segments) == 3
    for segment in segments:
        facts = probe(segment.path)
        assert facts.first_video_pts == 0
        assert facts.keyframe_count >= 1
        assert facts.decoded_video_frames == segment.video_frames
        # Matroska stores the rate approximately (19001/317 ~= 60000/1001).
        assert facts.video_rate is not None
        assert abs(float(facts.video_rate) - float(fps)) < 0.01


@pytest.mark.parametrize("fps", [Fraction(60, 1), Fraction(60000, 1001)])
def test_jittered_audio_timeline_is_decodable(media, tmp_path: Path, probe, fps) -> None:
    info = media.stream_info(fps=fps, width=64, height=36, sample_rate=48000, channels=2)
    frames = media.frames(
        duration_ns=6_500_000_000,
        fps=fps,
        width=64,
        height=36,
        sample_rate=48000,
        channels=2,
    )
    jitter_start = 50 * 1024
    jitter_ns = round(1_000_000_000 / 48000)
    jittered = []
    changed = False
    for frame in frames:
        if isinstance(frame, AudioFrame) and frame.timestamp_ns == round(
            jitter_start * 1_000_000_000 / 48000
        ):
            frame = replace(frame, timestamp_ns=frame.timestamp_ns - jitter_ns)
            changed = True
        jittered.append(frame)
    assert changed

    recorder = SegmentRecorder()
    recorder.start(media.session(tmp_path, info))
    segments: list[Segment] = []
    for frame in jittered:
        if isinstance(frame, VideoFrame):
            segments.extend(recorder.push_video(frame))
        else:
            recorder.push_audio(frame)
    last = recorder.finish()
    assert last is not None
    segments.append(last)
    recorder.close()

    assert len(segments) >= 3
    for segment in segments:
        facts = probe(segment.path)
        assert facts.audio_present
        assert facts.audio_samples == segment.audio_samples


def test_stream_layout_consistent_across_segments(media, tmp_path: Path, probe) -> None:
    fps = Fraction(60, 1)
    info = media.stream_info(fps=fps, width=64, height=36, sample_rate=48000, channels=2)
    recorder = SegmentRecorder()
    recorder.start(media.session(tmp_path, info))
    segments = _record(
        media,
        recorder,
        duration_ns=6_500_000_000,
        fps=fps,
        width=64,
        height=36,
        sample_rate=48000,
        channels=2,
    )
    recorder.close()

    assert len(segments) >= 3
    layouts = {
        (
            facts.video_codec,
            facts.width,
            facts.height,
            facts.pixel_format,
            facts.video_time_base,
            facts.video_rate,
            facts.audio_codec,
            facts.audio_sample_rate,
            facts.audio_channels,
            facts.audio_time_base,
        )
        for facts in (probe(segment.path) for segment in segments)
    }
    assert len(layouts) == 1


def test_video_only_media(media, tmp_path: Path, probe) -> None:
    fps = Fraction(60, 1)
    info = media.stream_info(fps=fps, width=64, height=36)
    recorder = SegmentRecorder()
    recorder.start(media.session(tmp_path, info))
    segments = _record(media, recorder, duration_ns=4_500_000_000, fps=fps, width=64, height=36)
    recorder.close()

    assert segments
    for segment in segments:
        facts = probe(segment.path)
        assert not facts.audio_present
        assert facts.audio_samples == 0
        assert segment.audio_samples == 0
        assert facts.decoded_video_frames == segment.video_frames
        assert facts.first_video_pts == 0
        assert facts.keyframe_count >= 1
