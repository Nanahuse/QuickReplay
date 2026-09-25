"""Fake NDI -> NdiInputSource -> SegmentRecorder -> MKV integration."""

from fractions import Fraction
from pathlib import Path
from uuid import uuid4

from fake_ndi import FakeBackend, fake_stream_script

from quickreplay.input.models import NdiInputConfig, VideoFrame
from quickreplay.input.ndi.source import NdiInputSource
from quickreplay.recording.models import RecordingSession, Segment
from quickreplay.recording.segment_recorder import SegmentRecorder

SEGMENT_DURATION_NS = 2_000_000_000


def _record(
    directory: Path,
    *,
    fps: Fraction,
    width: int,
    height: int,
    sample_rate: int | None,
    channels: int | None,
    duration_ns: int,
) -> tuple[list[Segment], object]:
    script = fake_stream_script(
        duration_ns=duration_ns,
        fps=fps,
        width=width,
        height=height,
        sample_rate=sample_rate,
        channels=channels,
    )
    backend = FakeBackend(sources=("HOST (Fake Source)",), script=script)
    source = NdiInputSource(
        NdiInputConfig(source_name="Fake Source"), backend=backend, discovery_timeout_ms=0
    )
    source.open()

    pending = []
    while source.stream_info is None or source.stream_info.audio is None:
        item = source.read()
        if item is None:
            break
        pending.append(item)
    info = source.stream_info
    assert info is not None

    recorder = SegmentRecorder(segment_duration_ns=SEGMENT_DURATION_NS)
    recorder.start(RecordingSession(uuid4(), info, 0, directory))
    segments: list[Segment] = []

    def feed(frame) -> None:
        if isinstance(frame, VideoFrame):
            segments.extend(recorder.push_video(frame))
        else:
            recorder.push_audio(frame)

    for frame in pending:
        feed(frame)
    while True:
        item = source.read()
        if item is None:
            break
        feed(item)

    last = recorder.finish()
    if last is not None:
        segments.append(last)
    recorder.close()
    source.close()
    return segments, info


def _check_segments(segments: list[Segment], info, probe, fps: Fraction) -> None:
    assert info.video.pixel_format == "UYVY"
    assert segments
    for segment in segments:
        facts = probe(segment.path)
        assert facts.video_codec == "h264"
        assert facts.first_video_pts == 0
        assert facts.keyframe_count >= 1
        assert facts.decoded_video_frames == segment.video_frames
        assert facts.audio_present
        assert facts.first_audio_pts == 0
        assert facts.audio_samples == segment.audio_samples
        assert abs(float(facts.video_rate) - float(fps)) < 0.01

    layouts = {probe(segment.path).video_time_base for segment in segments}
    assert len(layouts) == 1


def test_ndi_to_segment_recorder_60fps(tmp_path: Path, probe) -> None:
    fps = Fraction(60, 1)

    segments, info = _record(
        tmp_path,
        fps=fps,
        width=64,
        height=36,
        sample_rate=48000,
        channels=2,
        duration_ns=4_500_000_000,
    )

    assert len(segments) == 3
    assert sum(segment.video_frames for segment in segments) == 271
    assert sum(segment.audio_samples for segment in segments) == 216000
    _check_segments(segments, info, probe, fps)


def test_ndi_to_segment_recorder_5994fps(tmp_path: Path, probe) -> None:
    fps = Fraction(60000, 1001)

    segments, info = _record(
        tmp_path,
        fps=fps,
        width=64,
        height=36,
        sample_rate=48000,
        channels=2,
        duration_ns=4_500_000_000,
    )

    assert len(segments) == 3
    assert sum(segment.video_frames for segment in segments) == 270
    assert sum(segment.audio_samples for segment in segments) == 216000
    _check_segments(segments, info, probe, fps)
