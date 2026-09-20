"""Tests for audio routing, boundary splitting and continuity."""

from fractions import Fraction
from pathlib import Path

import pytest

from quickreplay.input.models import AudioFrame, VideoFrame
from quickreplay.recording.errors import SegmentFormatError
from quickreplay.recording.models import Segment
from quickreplay.recording.segment_recorder import SegmentRecorder

SAMPLE_RATE = 48000
CHANNELS = 2
FPS = Fraction(60, 1)


def _push_audio_range(media, recorder: SegmentRecorder, start_sample: int, end_sample: int) -> None:
    position = start_sample
    while position < end_sample:
        count = min(1024, end_sample - position)
        recorder.push_audio(
            media.audio(
                start_sample=position,
                sample_rate=SAMPLE_RATE,
                channels=CHANNELS,
                count=count,
            )
        )
        position += count


def test_audio_split_is_sample_exact(media, tmp_path: Path) -> None:
    info = media.stream_info(
        fps=FPS, width=64, height=36, sample_rate=SAMPLE_RATE, channels=CHANNELS
    )
    recorder = SegmentRecorder()
    recorder.start(media.session(tmp_path, info))
    # Large audio frames deliberately straddle the 2 s boundary.
    frames = media.frames(
        duration_ns=4_000_000_000,
        fps=FPS,
        width=64,
        height=36,
        sample_rate=SAMPLE_RATE,
        channels=CHANNELS,
        audio_frame_samples=4096,
    )
    segments: list[Segment] = []
    for frame in frames:
        if isinstance(frame, VideoFrame):
            segments.extend(recorder.push_video(frame))
        else:
            recorder.push_audio(frame)
    last = recorder.finish()
    assert last is not None
    segments.append(last)
    recorder.close()

    assert segments[0].audio_samples == 96000
    assert segments[1].audio_samples == 96000
    assert sum(segment.audio_samples for segment in segments) == 192000


def test_audio_total_samples(media, tmp_path: Path) -> None:
    info = media.stream_info(
        fps=FPS, width=64, height=36, sample_rate=SAMPLE_RATE, channels=CHANNELS
    )
    recorder = SegmentRecorder()
    recorder.start(media.session(tmp_path, info))
    frames = media.frames(
        duration_ns=4_000_000_000,
        fps=FPS,
        width=64,
        height=36,
        sample_rate=SAMPLE_RATE,
        channels=CHANNELS,
    )
    segments: list[Segment] = []
    for frame in frames:
        if isinstance(frame, VideoFrame):
            segments.extend(recorder.push_video(frame))
        else:
            recorder.push_audio(frame)
    last = recorder.finish()
    assert last is not None
    segments.append(last)
    recorder.close()

    assert sum(segment.audio_samples for segment in segments) == int(4.0 * SAMPLE_RATE)


def test_audio_continuity_and_local_pts(media, tmp_path: Path, probe) -> None:
    info = media.stream_info(
        fps=FPS, width=64, height=36, sample_rate=SAMPLE_RATE, channels=CHANNELS
    )
    recorder = SegmentRecorder()
    recorder.start(media.session(tmp_path, info))
    frames = media.frames(
        duration_ns=4_000_000_000,
        fps=FPS,
        width=64,
        height=36,
        sample_rate=SAMPLE_RATE,
        channels=CHANNELS,
    )
    segments: list[Segment] = []
    for frame in frames:
        if isinstance(frame, VideoFrame):
            segments.extend(recorder.push_video(frame))
        else:
            recorder.push_audio(frame)
    last = recorder.finish()
    assert last is not None
    segments.append(last)
    recorder.close()

    for segment in segments:
        facts = probe(segment.path)
        assert facts.audio_present
        assert facts.audio_samples == segment.audio_samples
        if segment.audio_samples > 0:
            assert facts.first_audio_pts == 0
    # No gap or overlap: the session-wide sample count is the sum of the parts.
    assert sum(segment.audio_samples for segment in segments) == 192000


def test_trailing_audio_is_trimmed(media, tmp_path: Path) -> None:
    info = media.stream_info(
        fps=FPS, width=64, height=36, sample_rate=SAMPLE_RATE, channels=CHANNELS
    )
    recorder = SegmentRecorder()
    recorder.start(media.session(tmp_path, info))

    # Video ends at 2.0 s (frame 120 starts the second segment); audio runs to 3 s.
    segments: list[Segment] = []
    total_audio = 3 * SAMPLE_RATE
    audio_pos = 0
    for index in range(121):
        video_ts = round(index * 1e9 / 60)
        while audio_pos < total_audio:
            frame = media.audio(
                start_sample=audio_pos,
                sample_rate=SAMPLE_RATE,
                channels=CHANNELS,
                count=min(1024, total_audio - audio_pos),
            )
            if frame.timestamp_ns > video_ts:
                break
            recorder.push_audio(frame)
            audio_pos += frame.sample_count
        segments.extend(recorder.push_video(media.video(index=index, fps=FPS, width=64, height=36)))
    # Audio after the last video frame (2.0 s .. 3.0 s).
    _push_audio_range(media, recorder, audio_pos, total_audio)
    last = recorder.finish()
    assert last is not None
    segments.append(last)
    recorder.close()

    # final end = 2.0 s + 1/60 s -> 96800 samples; the rest is trimmed.
    assert sum(segment.audio_samples for segment in segments) == 96800


def test_audio_before_first_video_is_trimmed(media, tmp_path: Path) -> None:
    info = media.stream_info(
        fps=FPS, width=64, height=36, sample_rate=SAMPLE_RATE, channels=CHANNELS
    )
    recorder = SegmentRecorder()
    recorder.start(media.session(tmp_path, info))

    # Audio arrives before any video; all of it is before the first video (1.0 s).
    _push_audio_range(media, recorder, 0, 19200)

    segments: list[Segment] = []
    for index in range(3):
        timestamp_ns = 1_000_000_000 + index * round(1e9 / 60)
        segments.extend(
            recorder.push_video(
                media.video_at(timestamp_ns=timestamp_ns, fps=FPS, width=64, height=36)
            )
        )
    last = recorder.finish()
    assert last is not None
    segments.append(last)
    recorder.close()

    assert sum(segment.audio_samples for segment in segments) == 0


def test_audio_ahead_of_video_splits_at_actual_boundary(media, tmp_path: Path) -> None:
    info = media.stream_info(
        fps=FPS, width=64, height=36, sample_rate=SAMPLE_RATE, channels=CHANNELS
    )
    recorder = SegmentRecorder()
    recorder.start(media.session(tmp_path, info))

    segments: list[Segment] = []
    # Video up to 1.95 s.
    for index in range(118):
        segments.extend(recorder.push_video(media.video(index=index, fps=FPS, width=64, height=36)))

    # Audio rushes ahead past the nominal 2 s boundary, up to 2.05 s.
    boundary_sample = round(2_050_000_000 / 1e9 * SAMPLE_RATE)
    _push_audio_range(media, recorder, 0, boundary_sample)

    # The actual boundary is the first video frame >= 2 s, at 2.05 s.
    segments.extend(
        recorder.push_video(
            media.video_at(timestamp_ns=2_050_000_000, fps=FPS, width=64, height=36)
        )
    )
    last = recorder.finish()
    assert last is not None
    segments.append(last)
    recorder.close()

    # Segment 0 must contain audio up to the *video* boundary, not the nominal one.
    assert segments[0].session_end_ns == 2_050_000_000
    assert segments[0].audio_samples == boundary_sample == 98400


def test_audio_frame_shape_mismatch_raises(media, tmp_path: Path) -> None:
    info = media.stream_info(
        fps=FPS, width=64, height=36, sample_rate=SAMPLE_RATE, channels=CHANNELS
    )
    recorder = SegmentRecorder()
    recorder.start(media.session(tmp_path, info))
    recorder.push_video(media.video(index=0, fps=FPS, width=64, height=36))

    # sample_count does not match the payload shape.
    payload = media.audio(
        start_sample=0, sample_rate=SAMPLE_RATE, channels=CHANNELS, count=1024
    ).data
    bad = AudioFrame(0, SAMPLE_RATE, CHANNELS, 999, payload)

    with pytest.raises(SegmentFormatError):
        recorder.push_audio(bad)
    recorder.close()
