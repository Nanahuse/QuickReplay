"""Fake InputSource and worker test harness for the recorder worker tests."""

import queue
import threading
import time
from collections.abc import Callable, Sequence
from fractions import Fraction
from typing import Any, TypeVar

import numpy as np

from quickreplay.input.models import (
    AudioFrame,
    AudioStreamInfo,
    InputConfig,
    StreamInfo,
    VideoFrame,
    VideoStreamInfo,
)
from quickreplay.recording.events import WorkerEvent, WorkerStateChanged
from quickreplay.recording.models import WorkerState
from quickreplay.replay.asset_builder import ReplayAssetBuilder
from quickreplay.units import NANOSECONDS_PER_SECOND, round_fraction
from quickreplay.worker.inputs import InputSourceHandle
from quickreplay.worker.runtime import RecorderWorkerRuntime
from quickreplay.worker.settings import RecorderWorkerSettings

EventT = TypeVar("EventT", bound=WorkerEvent)


def video_info(
    fps: Fraction, width: int = 64, height: int = 36, pixel_format: str = "BGR24"
) -> VideoStreamInfo:
    return VideoStreamInfo(width, height, fps, pixel_format)


def audio_info(sample_rate: int = 48000, channels: int = 2) -> AudioStreamInfo:
    return AudioStreamInfo(sample_rate, channels)


def video_frame(
    timestamp_ns: int, *, fps: Fraction, width: int = 64, height: int = 36, value: int = 0
) -> VideoFrame:
    data = np.full((height, width, 3), value % 256, dtype=np.uint8)
    return VideoFrame(timestamp_ns, width, height, fps, "BGR24", data)


def audio_frame(
    timestamp_ns: int, *, sample_rate: int = 48000, channels: int = 2, samples: int = 1024
) -> AudioFrame:
    data = np.zeros((channels, samples), dtype=np.float32)
    return AudioFrame(timestamp_ns, sample_rate, channels, samples, data)


def build_script(
    *,
    duration_ns: int,
    fps: Fraction,
    base_ns: int = 0,
    width: int = 64,
    height: int = 36,
    sample_rate: int | None = None,
    channels: int | None = None,
    audio_frame_samples: int = 1024,
    audio_delay_ns: int = 0,
) -> tuple[list[Any], int, int]:
    """Build an interleaved arrival script.

    Returns ``(script, video_frames, audio_samples)``.  Audio events are placed
    in arrival order at ``timestamp + audio_delay_ns`` while keeping their real
    timestamps, which models audio arriving later than video.
    """
    events: list[tuple[int, int, Any]] = []
    video_frames = 0
    index = 0
    while True:
        offset = round_fraction(Fraction(index * NANOSECONDS_PER_SECOND, 1) / fps)
        if offset > duration_ns:
            break
        timestamp_ns = base_ns + offset
        events.append(
            (offset, 0, video_frame(timestamp_ns, fps=fps, width=width, height=height, value=index))
        )
        video_frames += 1
        index += 1

    audio_samples = 0
    if sample_rate is not None and channels is not None:
        total = int(Fraction(duration_ns) * sample_rate / NANOSECONDS_PER_SECOND)
        position = 0
        while position < total:
            count = min(audio_frame_samples, total - position)
            offset = round_fraction(Fraction(position * NANOSECONDS_PER_SECOND, sample_rate))
            events.append(
                (
                    offset + audio_delay_ns,
                    1,
                    audio_frame(
                        base_ns + offset,
                        sample_rate=sample_rate,
                        channels=channels,
                        samples=count,
                    ),
                )
            )
            audio_samples += count
            position += count

    events.sort(key=lambda event: (event[0], event[1]))
    return [item for _key, _kind, item in events], video_frames, audio_samples


class FakeInputSource:
    """A scripted :class:`~quickreplay.input.source.InputSource`."""

    def __init__(
        self,
        script: Sequence[Any],
        *,
        video_stream: VideoStreamInfo,
        audio_stream: AudioStreamInfo | None = None,
    ) -> None:
        self._script = list(script)
        self._video_stream = video_stream
        self._audio_stream = audio_stream
        self._seen_video = False
        self._seen_audio = False
        self.open_count = 0
        self.close_count = 0

    def open(self) -> None:
        self.open_count += 1

    def read(self) -> VideoFrame | AudioFrame | None:
        while True:
            if not self._script:
                return None
            item = self._script.pop(0)
            if isinstance(item, BaseException):
                raise item
            if callable(item) and not isinstance(item, (VideoFrame, AudioFrame)):
                item()
                continue
            if isinstance(item, VideoFrame):
                self._seen_video = True
            elif isinstance(item, AudioFrame):
                self._seen_audio = True
            return item

    @property
    def stream_info(self) -> StreamInfo | None:
        if not self._seen_video:
            return None
        audio = self._audio_stream if self._seen_audio else None
        return StreamInfo(video=self._video_stream, audio=audio)

    def close(self) -> None:
        self.close_count += 1


class ScriptedInputFactory:
    """Creates a fresh :class:`FakeInputSource` per call with a new epoch."""

    def __init__(
        self,
        *,
        fps: Fraction = Fraction(60, 1),
        width: int = 64,
        height: int = 36,
        duration_ns: int = 1_500_000_000,
        supports_audio: bool = True,
        audio: bool = True,
        audio_delay_ns: int = 0,
    ) -> None:
        self.fps = fps
        self.width = width
        self.height = height
        self.duration_ns = duration_ns
        self.supports_audio = supports_audio
        self.audio = audio and supports_audio
        self.audio_delay_ns = audio_delay_ns
        self.calls = 0
        self.sources: list[FakeInputSource] = []
        self.video_frames = 0
        self.audio_samples = 0

    def __call__(self, _config: InputConfig) -> InputSourceHandle:
        base_ns = 1_000_000_000 + self.calls * 100_000_000_000
        self.calls += 1
        script, video_frames, audio_samples = build_script(
            duration_ns=self.duration_ns,
            fps=self.fps,
            base_ns=base_ns,
            width=self.width,
            height=self.height,
            sample_rate=48000 if self.audio else None,
            channels=2 if self.audio else None,
            audio_delay_ns=self.audio_delay_ns,
        )
        self.video_frames += video_frames
        self.audio_samples += audio_samples
        source = FakeInputSource(
            script,
            video_stream=video_info(self.fps, self.width, self.height),
            audio_stream=audio_info() if self.audio else None,
        )
        self.sources.append(source)
        return InputSourceHandle(source=source, supports_audio=self.supports_audio)


class WorkerHarness:
    """Runs :class:`RecorderWorkerRuntime` in-process over thread queues."""

    def __init__(
        self,
        settings: RecorderWorkerSettings,
        *,
        input_factory: Callable[[InputConfig], InputSourceHandle],
        discovery: Callable[..., tuple[Any, ...]] | None = None,
        builder_factory: Callable[[], ReplayAssetBuilder] = ReplayAssetBuilder,
    ) -> None:
        self.commands: queue.Queue[Any] = queue.Queue()
        self.events: queue.Queue[WorkerEvent] = queue.Queue()
        self.seen: list[WorkerEvent] = []
        self.runtime = RecorderWorkerRuntime(
            settings,
            command_queue=self.commands,
            emit=self._emit,
            input_factory=input_factory,
            discovery=discovery or (lambda **_kwargs: ()),
            builder_factory=builder_factory,
        )
        self.thread = threading.Thread(target=self.runtime.run, daemon=True)

    def _emit(self, event: WorkerEvent) -> None:
        self.seen.append(event)
        self.events.put(event)

    def join(self, timeout: float = 10.0) -> None:
        self.thread.join(timeout)

    def start(self) -> None:
        self.thread.start()

    def send(self, command: Any) -> None:
        self.commands.put(command)

    def wait_event(
        self,
        event_type: type[EventT],
        *,
        predicate: Callable[[EventT], bool] | None = None,
        timeout: float = 10.0,
        description: str | None = None,
    ) -> EventT:
        label = description or event_type.__name__
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                event = self.events.get(timeout=0.05)
            except queue.Empty:
                continue
            if isinstance(event, event_type) and (predicate is None or predicate(event)):
                return event
        recent = [type(event).__name__ for event in self.seen[-8:]]
        raise AssertionError(f"timed out waiting for {label}; recent events: {recent}")

    def wait_state(self, state: WorkerState, *, timeout: float = 10.0) -> None:
        self.wait_event(
            WorkerStateChanged,
            predicate=lambda event: event.state == state,
            timeout=timeout,
            description=f"state {state}",
        )

    def shutdown(self) -> None:
        self.send(_shutdown())
        self.thread.join(timeout=10.0)


def _shutdown() -> Any:
    from quickreplay.recording.commands import Shutdown

    return Shutdown()
