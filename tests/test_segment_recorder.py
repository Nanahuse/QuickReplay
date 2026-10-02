"""Tests for segment rotation, metadata and recorder lifecycle."""

from collections.abc import Iterable
from fractions import Fraction
from pathlib import Path

import pytest

from quickreplay.input.models import AudioFrame, VideoFrame
from quickreplay.recording.errors import (
    SegmentEncodingError,
    SegmentFormatError,
    SegmentTimestampError,
)
from quickreplay.recording.models import Segment
from quickreplay.recording.segment_recorder import SegmentRecorder


def _record(recorder: SegmentRecorder, frames: Iterable[VideoFrame | AudioFrame]) -> list[Segment]:
    produced: list[Segment] = []
    for frame in frames:
        if isinstance(frame, VideoFrame):
            produced.extend(recorder.push_video(frame))
        else:
            recorder.push_audio(frame)
    last = recorder.finish()
    if last is not None:
        produced.append(last)
    return produced


def test_rotation_is_time_based(media, tmp_path: Path) -> None:
    fps = Fraction(60, 1)
    info = media.stream_info(fps=fps, width=64, height=36, sample_rate=48000, channels=2)
    recorder = SegmentRecorder()
    recorder.start(media.session(tmp_path, info))
    frames = media.frames(
        duration_ns=4_500_000_000, fps=fps, width=64, height=36, sample_rate=48000, channels=2
    )
    segments = _record(recorder, frames)
    recorder.close()

    assert [segment.id for segment in segments] == [0, 1, 2]
    assert segments[0].session_start_ns == 0
    assert segments[0].session_end_ns == 2_000_000_000
    assert segments[1].session_start_ns == 2_000_000_000
    assert segments[1].session_end_ns == 4_000_000_000
    assert segments[2].session_start_ns == 4_000_000_000
    assert 0 < segments[2].duration_ns < 2_000_000_000
    for previous, following in zip(segments, segments[1:], strict=False):
        assert previous.session_end_ns == following.session_start_ns
    assert segments[0].video_frames == 120
    assert segments[1].video_frames == 120
    assert [segment.path.name for segment in segments] == [
        "segment_000000.mkv",
        "segment_000001.mkv",
        "segment_000002.mkv",
    ]
    assert all(segment.path.exists() for segment in segments)
    assert not list(tmp_path.glob("*.tmp.mkv"))


def test_rotation_uses_timestamps_not_frame_count(media, tmp_path: Path) -> None:
    fps = Fraction(60, 1)
    info = media.stream_info(fps=fps, width=64, height=36)
    recorder = SegmentRecorder()
    recorder.start(media.session(tmp_path, info))

    # The threshold is crossed on the 6th frame, not at a fixed count.
    timestamps_ns = [
        0,
        950_000_000,
        1_900_000_000,
        1_950_000_000,
        1_983_000_000,
        2_050_000_000,
        2_100_000_000,
    ]
    segments: list[Segment] = []
    for timestamp_ns in timestamps_ns:
        frame = media.video_at(timestamp_ns=timestamp_ns, fps=fps, width=64, height=36)
        segments.extend(recorder.push_video(frame))
    last = recorder.finish()
    assert last is not None
    segments.append(last)
    recorder.close()

    assert len(segments) == 2
    assert segments[0].video_frames == 5
    assert segments[1].video_frames == 2
    assert segments[0].session_end_ns == 2_050_000_000
    assert segments[1].session_start_ns == 2_050_000_000


def test_rotation_5994fps(media, tmp_path: Path) -> None:
    fps = Fraction(60000, 1001)
    info = media.stream_info(fps=fps, width=64, height=36)
    recorder = SegmentRecorder()
    recorder.start(media.session(tmp_path, info))
    frames = media.frames(duration_ns=4_500_000_000, fps=fps, width=64, height=36)
    segments = _record(recorder, frames)
    recorder.close()

    assert len(segments) == 3
    frame_120 = media.video(index=120, fps=fps, width=64, height=36)
    assert segments[1].session_start_ns == frame_120.timestamp_ns
    assert segments[1].session_start_ns >= 2_000_000_000
    assert segments[0].video_frames == 120


def test_partial_final_segment_is_kept(media, tmp_path: Path) -> None:
    fps = Fraction(60, 1)
    info = media.stream_info(fps=fps, width=64, height=36)
    recorder = SegmentRecorder()
    recorder.start(media.session(tmp_path, info))
    frames = media.frames(duration_ns=4_500_000_000, fps=fps, width=64, height=36)
    segments = _record(recorder, frames)
    recorder.close()

    assert len(segments) == 3
    assert segments[2].duration_ns < 2_000_000_000
    assert segments[2].video_frames > 0


def test_video_only_recording(media, tmp_path: Path) -> None:
    fps = Fraction(60, 1)
    info = media.stream_info(fps=fps, width=64, height=36)
    recorder = SegmentRecorder()
    recorder.start(media.session(tmp_path, info))
    frames = media.frames(duration_ns=4_500_000_000, fps=fps, width=64, height=36)
    segments = _record(recorder, frames)
    recorder.close()

    assert segments
    assert all(segment.audio_samples == 0 for segment in segments)
    assert all(segment.path.exists() for segment in segments)


def test_no_video_returns_none(media, tmp_path: Path) -> None:
    info = media.stream_info(
        fps=Fraction(60, 1), width=64, height=36, sample_rate=48000, channels=2
    )
    recorder = SegmentRecorder()
    recorder.start(media.session(tmp_path, info))
    for index in range(5):
        recorder.push_audio(
            media.audio(start_sample=index * 1024, sample_rate=48000, channels=2, count=1024)
        )

    assert recorder.finish() is None
    recorder.close()
    assert not list(tmp_path.glob("*.mkv"))
    assert not list(tmp_path.glob("*.tmp.mkv"))


def test_close_without_finish_does_not_publish(media, tmp_path: Path) -> None:
    fps = Fraction(60, 1)
    info = media.stream_info(fps=fps, width=64, height=36)
    recorder = SegmentRecorder()
    recorder.start(media.session(tmp_path, info))
    recorder.push_video(media.video(index=0, fps=fps, width=64, height=36))
    recorder.close()
    recorder.close()  # idempotent

    assert not list(tmp_path.glob("*.mkv"))
    assert not list(tmp_path.glob("*.tmp.mkv"))


@pytest.mark.parametrize(
    "width,height,fps,pixel_format",
    [
        (128, 36, Fraction(60, 1), "RGB24"),
        (64, 72, Fraction(60, 1), "RGB24"),
        (64, 36, Fraction(30, 1), "RGB24"),
        (64, 36, Fraction(60, 1), "BGR24"),
    ],
)
def test_video_format_mismatch_raises(
    media, tmp_path: Path, width: int, height: int, fps: Fraction, pixel_format: str
) -> None:
    info = media.stream_info(fps=Fraction(60, 1), width=64, height=36, pixel_format="RGB24")
    recorder = SegmentRecorder()
    recorder.start(media.session(tmp_path, info))
    recorder.push_video(media.video(index=0, fps=Fraction(60, 1), width=64, height=36))

    bad = media.video_at(
        timestamp_ns=20_000_000, fps=fps, width=width, height=height, pixel_format=pixel_format
    )
    with pytest.raises(SegmentFormatError):
        recorder.push_video(bad)
    recorder.close()


def test_audio_format_mismatch_raises(media, tmp_path: Path) -> None:
    info = media.stream_info(
        fps=Fraction(60, 1), width=64, height=36, sample_rate=48000, channels=2
    )
    recorder = SegmentRecorder()
    recorder.start(media.session(tmp_path, info))
    recorder.push_video(media.video(index=0, fps=Fraction(60, 1), width=64, height=36))

    with pytest.raises(SegmentFormatError):
        recorder.push_audio(media.audio(start_sample=0, sample_rate=44100, channels=2, count=1024))
    with pytest.raises(SegmentFormatError):
        recorder.push_audio(media.audio(start_sample=0, sample_rate=48000, channels=1, count=1024))
    recorder.close()


def test_video_timestamp_regression_raises(media, tmp_path: Path) -> None:
    fps = Fraction(60, 1)
    info = media.stream_info(fps=fps, width=64, height=36)
    recorder = SegmentRecorder()
    recorder.start(media.session(tmp_path, info))
    recorder.push_video(media.video_at(timestamp_ns=1_000_000_000, fps=fps, width=64, height=36))

    with pytest.raises(SegmentTimestampError):
        recorder.push_video(media.video_at(timestamp_ns=500_000_000, fps=fps, width=64, height=36))
    recorder.close()


def test_audio_timestamp_regression_raises(media, tmp_path: Path) -> None:
    info = media.stream_info(
        fps=Fraction(60, 1), width=64, height=36, sample_rate=48000, channels=2
    )
    recorder = SegmentRecorder()
    recorder.start(media.session(tmp_path, info))
    recorder.push_video(media.video(index=0, fps=Fraction(60, 1), width=64, height=36))
    recorder.push_audio(media.audio(start_sample=2048, sample_rate=48000, channels=2, count=1024))

    with pytest.raises(SegmentTimestampError):
        recorder.push_audio(media.audio(start_sample=0, sample_rate=48000, channels=2, count=1024))
    recorder.close()


def test_timestamp_before_epoch_raises(media, tmp_path: Path) -> None:
    fps = Fraction(60, 1)
    info = media.stream_info(fps=fps, width=64, height=36)
    recorder = SegmentRecorder()
    recorder.start(media.session(tmp_path, info, epoch_ns=1_000_000_000))

    with pytest.raises(SegmentTimestampError):
        recorder.push_video(media.video_at(timestamp_ns=0, fps=fps, width=64, height=36))
    recorder.close()


class ExplodingWriter:
    """Test double that fails while finalizing and cleans up after itself."""

    def __init__(self, segment_id: int, directory: Path, stream_info: object) -> None:
        self.tmp_path = Path(directory) / f"segment_{segment_id:06d}.tmp.mkv"
        self.tmp_path.write_bytes(b"partial")

    def write_video(self, frame: VideoFrame, pts: int) -> None:
        pass

    def write_audio(self, data: object, pts: int) -> None:
        pass

    def finalize(self) -> Path:
        raise SegmentEncodingError("injected finalize failure")

    def abort(self) -> None:
        self.tmp_path.unlink(missing_ok=True)


def test_failure_cleanup_leaves_no_partial_segment(media, tmp_path: Path) -> None:
    fps = Fraction(60, 1)
    info = media.stream_info(fps=fps, width=64, height=36)

    def factory(segment_id: int, directory: Path, stream_info: object) -> ExplodingWriter:
        return ExplodingWriter(segment_id, directory, stream_info)

    recorder = SegmentRecorder(writer_factory=factory)
    recorder.start(media.session(tmp_path, info))

    segments: list[Segment] = []
    with pytest.raises(SegmentEncodingError):
        # Frame 120 crosses the 2 s boundary, forcing finalize of segment 0.
        for index in range(121):
            segments.extend(
                recorder.push_video(media.video(index=index, fps=fps, width=64, height=36))
            )
    recorder.close()

    assert segments == []
    assert not list(tmp_path.glob("*.mkv"))
    assert not list(tmp_path.glob("*.tmp.mkv"))
