"""RecordingPipeline: bootstrap, A/V ordering, hold-back and failures."""

import time
from collections.abc import Callable
from fractions import Fraction
from pathlib import Path

import pytest
from fake_worker_input import (
    FakeInputSource,
    audio_frame,
    audio_info,
    build_script,
    video_frame,
    video_info,
)

from quickreplay.input.models import NdiInputConfig
from quickreplay.units import NANOSECONDS_PER_SECOND, round_fraction
from quickreplay.worker.errors import (
    PipelineFormatChangeError,
    PipelineOrderingError,
    PipelineStartupError,
)
from quickreplay.worker.inputs import InputSourceHandle
from quickreplay.worker.pipeline import RecordingPipeline
from quickreplay.worker.settings import RecorderWorkerSettings

FPS = Fraction(60, 1)


def _pipeline(
    tmp_path: Path,
    source: FakeInputSource,
    *,
    supports_audio: bool,
    **overrides: int,
) -> RecordingPipeline:
    options: dict[str, int] = {"video_queue_capacity": 4096, "audio_queue_capacity": 4096}
    options.update(overrides)
    settings = RecorderWorkerSettings(working_directory=tmp_path, **options)
    handle = InputSourceHandle(source=source, supports_audio=supports_audio)
    return RecordingPipeline(settings, input_factory=lambda _config: handle)


def _wait_until(predicate: Callable[[], bool], *, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition was not met in time")


def test_first_video_is_epoch_and_nothing_is_dropped(tmp_path: Path) -> None:
    script, video_frames, _ = build_script(
        duration_ns=1_000_000_000, fps=FPS, base_ns=5_000_000_000
    )
    source = FakeInputSource(script, video_stream=video_info(FPS))
    pipeline = _pipeline(tmp_path, source, supports_audio=False)
    pipeline.start(NdiInputConfig("fake"))
    try:
        session = pipeline.session
        assert session is not None
        assert session.epoch_ns == 5_000_000_000
        _wait_until(lambda: pipeline.metrics().recorded_video_frames >= video_frames)
    finally:
        pipeline.stop()
    assert pipeline.poll_fatal() is None
    ring = pipeline.take_ring()
    assert ring is not None
    assert sum(segment.video_frames for segment in ring.segments) == video_frames


def test_delayed_audio_within_holdback_records(tmp_path: Path) -> None:
    script, video_frames, audio_samples = build_script(
        duration_ns=2_000_000_000,
        fps=FPS,
        sample_rate=48000,
        channels=2,
        audio_delay_ns=200_000_000,
    )
    source = FakeInputSource(script, video_stream=video_info(FPS), audio_stream=audio_info())
    pipeline = _pipeline(tmp_path, source, supports_audio=True)
    pipeline.start(NdiInputConfig("fake"))
    try:
        _wait_until(lambda: pipeline.metrics().captured_audio_samples >= audio_samples, timeout=5.0)
        pipeline.stop()
    finally:
        pipeline.abort()
    assert pipeline.poll_fatal() is None
    metrics = pipeline.metrics()
    assert metrics.recorded_video_frames == video_frames
    assert metrics.recorded_audio_samples == audio_samples


def test_late_frame_beyond_holdback_is_an_ordering_error(tmp_path: Path) -> None:
    items: list[tuple[int, int, object]] = [
        (0, 1, audio_frame(0)),
        (0, 0, video_frame(0, fps=FPS)),
        (20_000_000, 1, audio_frame(20_000_000)),
    ]
    index = 1
    while True:
        offset = round_fraction(Fraction(index * NANOSECONDS_PER_SECOND, 1) / FPS)
        if offset > 1_000_000_000:
            break
        items.append((offset, 0, video_frame(offset, fps=FPS)))
        index += 1
    # This audio is delivered late and rewinds the audio stream.
    items.append((1_500_000_000, 1, audio_frame(10_000_000)))
    items.sort(key=lambda entry: (entry[0], entry[1]))
    source = FakeInputSource(
        [item for _key, _kind, item in items],
        video_stream=video_info(FPS),
        audio_stream=audio_info(),
    )
    pipeline = _pipeline(tmp_path, source, supports_audio=True)
    pipeline.start(NdiInputConfig("fake"))
    try:
        _wait_until(lambda: pipeline.poll_fatal() is not None, timeout=5.0)
        fatal = pipeline.poll_fatal()
    finally:
        pipeline.abort()
    assert isinstance(fatal, PipelineOrderingError)


def test_audio_after_video_only_session_is_a_format_change(tmp_path: Path) -> None:
    script, _video_frames, _audio_samples = build_script(duration_ns=1_500_000_000, fps=FPS)
    script.append(audio_frame(1_600_000_000))
    source = FakeInputSource(script, video_stream=video_info(FPS), audio_stream=audio_info())
    pipeline = _pipeline(tmp_path, source, supports_audio=True)
    pipeline.start(NdiInputConfig("fake"))
    try:
        _wait_until(lambda: pipeline.poll_fatal() is not None, timeout=5.0)
        fatal = pipeline.poll_fatal()
    finally:
        pipeline.abort()
    assert isinstance(fatal, PipelineFormatChangeError)


def test_camera_video_only_has_no_holdback(tmp_path: Path) -> None:
    script, video_frames, _ = build_script(duration_ns=1_000_000_000, fps=FPS)
    source = FakeInputSource(script, video_stream=video_info(FPS))
    pipeline = _pipeline(
        tmp_path, source, supports_audio=False, av_reorder_holdback_ns=5_000_000_000
    )
    pipeline.start(NdiInputConfig("fake"))
    try:
        _wait_until(lambda: pipeline.metrics().recorded_video_frames > 0, timeout=3.0)
    finally:
        pipeline.stop()
    assert pipeline.poll_fatal() is None
    assert pipeline.metrics().recorded_video_frames == video_frames


def test_capture_failure_becomes_fatal(tmp_path: Path) -> None:
    source = FakeInputSource(
        [video_frame(0, fps=FPS), ValueError("capture exploded")],
        video_stream=video_info(FPS),
    )
    pipeline = _pipeline(tmp_path, source, supports_audio=False)
    pipeline.start(NdiInputConfig("fake"))
    try:
        _wait_until(lambda: pipeline.poll_fatal() is not None, timeout=5.0)
        fatal = pipeline.poll_fatal()
    finally:
        pipeline.abort()
    assert isinstance(fatal, ValueError)


def test_startup_timeout_without_video(tmp_path: Path) -> None:
    source = FakeInputSource([], video_stream=video_info(FPS))
    pipeline = _pipeline(
        tmp_path, source, supports_audio=False, stream_start_timeout_ns=200_000_000
    )

    with pytest.raises(PipelineStartupError):
        pipeline.start(NdiInputConfig("fake"))


def test_pre_epoch_audio_is_dropped(tmp_path: Path) -> None:
    epoch = 1_000_000_000
    items = [
        audio_frame(0),  # before the first video -> dropped
        video_frame(epoch, fps=FPS),
        video_frame(epoch + 16_000_000, fps=FPS),
        audio_frame(epoch),  # at the epoch -> kept
    ]
    source = FakeInputSource(items, video_stream=video_info(FPS), audio_stream=audio_info())
    pipeline = _pipeline(tmp_path, source, supports_audio=True)
    pipeline.start(NdiInputConfig("fake"))
    try:
        _wait_until(lambda: pipeline.metrics().captured_audio_samples >= 1024, timeout=5.0)
        pipeline.stop()
    finally:
        pipeline.abort()
    assert pipeline.poll_fatal() is None
    assert pipeline.metrics().captured_audio_samples == 1024
