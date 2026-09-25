"""Fake NDI backend for tests.

It implements the :class:`~quickreplay.input.ndi.backend.NdiBackend` protocol
with plain Python objects, so discovery, receiver lifecycle, capture, frame
freeing and timestamp handling can all be exercised in CI without an NDI
runtime or a real source.
"""

from collections.abc import Sequence
from fractions import Fraction
from typing import Any

import numpy as np

from quickreplay.input.ndi.backend import RawAudio, RawMetadata, RawVideo
from quickreplay.units import NANOSECONDS_PER_SECOND, round_fraction

DEFAULT_SCRIPT_LENGTH = 6000
"""Upper bound on the number of raw frames a fake script may hold."""


class FakeNativeBuffer:
    """Stands in for native NDI memory.  ``freed`` records the free step."""

    def __init__(self, data: Any) -> None:
        self.data = data
        self.freed = False


class FakeReceiver:
    """A scripted receiver.  Items are returned in order, then ``None``."""

    def __init__(self, script: Sequence[Any], source_name: str) -> None:
        self._script = list(script)
        self._source_name = source_name
        self.destroyed = False
        self.video_frees = 0
        self.audio_frees = 0
        self.metadata_frees = 0

    def capture(self, *, timeout_ms: int) -> Any:
        if not self._script:
            return None
        item = self._script.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    def free_video(self, frame: RawVideo) -> None:
        self.video_frees += 1
        if isinstance(frame.handle, FakeNativeBuffer):
            frame.handle.freed = True

    def free_audio(self, frame: RawAudio) -> None:
        self.audio_frees += 1
        if isinstance(frame.handle, FakeNativeBuffer):
            frame.handle.freed = True

    def free_metadata(self, frame: RawMetadata) -> None:
        self.metadata_frees += 1
        if isinstance(frame.handle, FakeNativeBuffer):
            frame.handle.freed = True

    def source_name(self) -> str:
        return self._source_name

    def destroy(self) -> None:
        self.destroyed = True


class FakeBackend:
    """A scripted :class:`NdiBackend`."""

    def __init__(
        self,
        *,
        sources: Sequence[str] = (),
        script: Sequence[Any] = (),
        receiver_error: BaseException | None = None,
    ) -> None:
        self.sources = tuple(sources)
        self._script = list(script)
        self._receiver_error = receiver_error
        self.initialize_calls = 0
        self.shutdown_calls = 0
        self.create_receiver_calls = 0
        self.receivers: list[FakeReceiver] = []

    def initialize(self) -> None:
        self.initialize_calls += 1

    def shutdown(self) -> None:
        self.shutdown_calls += 1

    def discover(self, *, timeout_ms: int) -> tuple[str, ...]:
        return self.sources

    def create_receiver(self, *, source_name: str, timeout_ms: int) -> FakeReceiver:
        self.create_receiver_calls += 1
        if self._receiver_error is not None:
            raise self._receiver_error
        receiver = FakeReceiver(self._script, source_name)
        self.receivers.append(receiver)
        return receiver


def fake_video(
    *,
    width: int = 4,
    height: int = 2,
    stride: int | None = None,
    timestamp_ns: int = 0,
    fps: Fraction = Fraction(60, 1),
    data: np.ndarray | None = None,
    pixel_format: str = "UYVY",
) -> RawVideo:
    if stride is None:
        stride = width * (4 if pixel_format.upper() == "BGRA" else 2)
    if data is None:
        data = np.arange(height * stride, dtype=np.uint8).reshape(height, stride)
    return RawVideo(
        width=width,
        height=height,
        line_stride=stride,
        pixel_format=pixel_format,
        fps=fps,
        timestamp_ns=timestamp_ns,
        data=data,
        handle=FakeNativeBuffer(data),
    )


def fake_audio(
    *,
    sample_rate: int = 48000,
    channels: int = 2,
    samples: int = 800,
    timestamp_ns: int = 0,
    data: np.ndarray | None = None,
    audio_format: str = "FLTP",
) -> RawAudio:
    if data is None:
        data = np.zeros((channels, samples), dtype=np.float32)
    return RawAudio(
        sample_rate=sample_rate,
        channels=channels,
        samples=samples,
        channel_stride=samples * 4,
        audio_format=audio_format,
        timestamp_ns=timestamp_ns,
        data=data,
        handle=FakeNativeBuffer(data),
    )


def fake_metadata() -> RawMetadata:
    return RawMetadata(handle=FakeNativeBuffer(b""))


def fake_stream_script(
    *,
    duration_ns: int,
    fps: Fraction,
    width: int,
    height: int,
    sample_rate: int | None = None,
    channels: int | None = None,
    audio_frame_samples: int = 1024,
    script_length: int = DEFAULT_SCRIPT_LENGTH,
) -> list[Any]:
    """Build an interleaved video/audio script like the media fixture."""
    events: list[tuple[int, int, Any]] = []

    total_video = int(Fraction(duration_ns) * fps / NANOSECONDS_PER_SECOND) + 1
    for index in range(total_video):
        offset = round_fraction(Fraction(index * NANOSECONDS_PER_SECOND, 1) / fps)
        if offset > duration_ns:
            break
        payload = np.full((height, width * 2), index % 256, dtype=np.uint8)
        events.append(
            (
                offset,
                0,
                fake_video(width=width, height=height, fps=fps, timestamp_ns=offset, data=payload),
            )
        )

    if sample_rate is not None and channels is not None:
        total_samples = int(Fraction(duration_ns) * sample_rate / NANOSECONDS_PER_SECOND)
        position = 0
        while position < total_samples:
            count = min(audio_frame_samples, total_samples - position)
            offset = round_fraction(Fraction(position * NANOSECONDS_PER_SECOND, sample_rate))
            data = np.zeros((channels, count), dtype=np.float32)
            events.append(
                (
                    offset,
                    1,
                    fake_audio(
                        sample_rate=sample_rate,
                        channels=channels,
                        samples=count,
                        timestamp_ns=offset,
                        data=data,
                    ),
                )
            )
            position += count

    events.sort(key=lambda event: (event[0], event[1]))
    return [item for _offset, _kind, item in events[:script_length]]
