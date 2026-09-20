"""Fake camera -> CameraInputSource -> SegmentRecorder -> video-only MKV."""

from fractions import Fraction
from pathlib import Path
from uuid import uuid4

from fake_camera import FakeCameraBackend, FakeCapture, bgr_frame, frame_clock

from quickreplay.input.camera.backend import CameraProperty
from quickreplay.input.camera.source import CameraInputSource
from quickreplay.input.models import CameraInputConfig, VideoFrame
from quickreplay.recording.models import RecordingSession, Segment
from quickreplay.recording.segment_recorder import SegmentRecorder
from quickreplay.units import NANOSECONDS_PER_SECOND, round_fraction

SEGMENT_DURATION_NS = 2_000_000_000


def _record(
    directory: Path,
    *,
    fps: Fraction,
    width: int,
    height: int,
    duration_ns: int,
) -> tuple[list[Segment], object]:
    offsets: list[int] = []
    index = 0
    while True:
        offset = round_fraction(Fraction(index * NANOSECONDS_PER_SECOND, 1) / fps)
        if offset > duration_ns:
            break
        offsets.append(offset)
        index += 1

    capture = FakeCapture(
        opened=True,
        frames=[bgr_frame(width, height, i % 256) for i in range(len(offsets))],
        properties={CameraProperty.FPS: float(fps)},
    )
    backend = FakeCameraBackend(lambda _index, _api: capture)
    source = CameraInputSource(
        CameraInputConfig(device_name="Camera 0", device_index=0, backend="any"),
        backend=backend,
        clock_ns=frame_clock(fps=fps),
    )
    source.open()

    recorder: SegmentRecorder | None = None
    info = None
    segments: list[Segment] = []
    for _ in range(len(offsets)):
        frame = source.read()
        assert isinstance(frame, VideoFrame)
        if recorder is None:
            info = source.stream_info
            assert info is not None
            assert info.audio is None
            recorder = SegmentRecorder(segment_duration_ns=SEGMENT_DURATION_NS)
            recorder.start(RecordingSession(uuid4(), info, frame.timestamp_ns, directory))
        segments.extend(recorder.push_video(frame))

    assert recorder is not None
    last = recorder.finish()
    if last is not None:
        segments.append(last)
    recorder.close()
    source.close()
    return segments, info


def _check(segments: list[Segment], info, probe, fps: Fraction) -> None:
    assert info.video.pixel_format == "BGR24"
    assert segments
    for segment in segments:
        facts = probe(segment.path)
        assert facts.video_codec == "h264"
        assert facts.first_video_pts == 0
        assert facts.keyframe_count >= 1
        assert facts.decoded_video_frames == segment.video_frames
        assert not facts.audio_present
        assert facts.audio_samples == 0
        assert segment.audio_samples == 0
        assert abs(float(facts.video_rate) - float(fps)) < 0.01


def test_camera_to_segment_recorder_60fps(tmp_path: Path, probe) -> None:
    fps = Fraction(60, 1)

    segments, info = _record(tmp_path, fps=fps, width=64, height=36, duration_ns=4_500_000_000)

    assert len(segments) == 3
    assert sum(segment.video_frames for segment in segments) == 271
    _check(segments, info, probe, fps)


def test_camera_to_segment_recorder_5994fps(tmp_path: Path, probe) -> None:
    fps = Fraction(60000, 1001)

    segments, info = _record(tmp_path, fps=fps, width=64, height=36, duration_ns=4_500_000_000)

    assert len(segments) == 3
    assert sum(segment.video_frames for segment in segments) == 270
    _check(segments, info, probe, fps)
