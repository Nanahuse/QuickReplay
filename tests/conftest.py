"""Shared fixtures for synthetic media used by the segment recorder tests."""

from collections.abc import Callable
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from uuid import uuid4

import av
import numpy as np
import pytest

from quickreplay.input.models import (
    AudioFrame,
    AudioStreamInfo,
    StreamInfo,
    VideoFrame,
    VideoStreamInfo,
)
from quickreplay.recording.models import RecordingSession, Segment
from quickreplay.units import NANOSECONDS_PER_SECOND, round_fraction

_VIDEO_COMPONENTS = {"RGB24": 3, "BGR24": 3, "RGBA": 4, "BGRA": 4, "GRAY8": 1}


class MediaFactory:
    """Generate timestamped domain frames without any hardware."""

    def video(
        self,
        *,
        index: int,
        fps: Fraction,
        width: int,
        height: int,
        pixel_format: str = "RGB24",
        value: int | None = None,
    ) -> VideoFrame:
        timestamp_ns = round_fraction(Fraction(index * NANOSECONDS_PER_SECOND, 1) / fps)
        components = _VIDEO_COMPONENTS[pixel_format]
        shape = (height, width) if components == 1 else (height, width, components)
        if value is None:
            value = index % 256
        data = np.full(shape, value, dtype=np.uint8)
        return VideoFrame(timestamp_ns, width, height, fps, pixel_format, data)

    def video_at(
        self,
        *,
        timestamp_ns: int,
        fps: Fraction,
        width: int,
        height: int,
        pixel_format: str = "RGB24",
    ) -> VideoFrame:
        components = _VIDEO_COMPONENTS[pixel_format]
        shape = (height, width) if components == 1 else (height, width, components)
        data = np.zeros(shape, dtype=np.uint8)
        return VideoFrame(timestamp_ns, width, height, fps, pixel_format, data)

    def audio(
        self,
        *,
        start_sample: int,
        sample_rate: int,
        channels: int,
        count: int,
        value: float = 0.0,
    ) -> AudioFrame:
        timestamp_ns = round_fraction(Fraction(start_sample, sample_rate) * NANOSECONDS_PER_SECOND)
        data = np.full((channels, count), value, dtype=np.float32)
        return AudioFrame(timestamp_ns, sample_rate, channels, count, data)

    def stream_info(
        self,
        *,
        fps: Fraction,
        width: int,
        height: int,
        pixel_format: str = "RGB24",
        sample_rate: int | None = None,
        channels: int | None = None,
    ) -> StreamInfo:
        audio = None
        if sample_rate is not None and channels is not None:
            audio = AudioStreamInfo(sample_rate, channels)
        return StreamInfo(VideoStreamInfo(width, height, fps, pixel_format), audio)

    def session(
        self, directory: Path, stream_info: StreamInfo, epoch_ns: int = 0
    ) -> RecordingSession:
        return RecordingSession(uuid4(), stream_info, epoch_ns, directory)

    def frames(
        self,
        *,
        duration_ns: int,
        fps: Fraction,
        width: int,
        height: int,
        pixel_format: str = "RGB24",
        sample_rate: int | None = None,
        channels: int | None = None,
        audio_frame_samples: int = 1024,
    ) -> list[VideoFrame | AudioFrame]:
        """Return video and audio frames interleaved in timestamp order."""
        events: list[tuple[int, int, VideoFrame | AudioFrame]] = []

        total_video = int(Fraction(duration_ns) * fps / NANOSECONDS_PER_SECOND) + 1
        for index in range(total_video):
            timestamp_ns = round_fraction(Fraction(index * NANOSECONDS_PER_SECOND, 1) / fps)
            if timestamp_ns > duration_ns:
                break
            events.append(
                (
                    timestamp_ns,
                    0,
                    self.video(
                        index=index, fps=fps, width=width, height=height, pixel_format=pixel_format
                    ),
                )
            )

        if sample_rate is not None and channels is not None:
            total_samples = int(Fraction(duration_ns) * sample_rate / NANOSECONDS_PER_SECOND)
            position = 0
            while position < total_samples:
                count = min(audio_frame_samples, total_samples - position)
                timestamp_ns = round_fraction(
                    Fraction(position * NANOSECONDS_PER_SECOND, sample_rate)
                )
                events.append(
                    (
                        timestamp_ns,
                        1,
                        self.audio(
                            start_sample=position,
                            sample_rate=sample_rate,
                            channels=channels,
                            count=count,
                        ),
                    )
                )
                position += count

        # Video sorts before audio at equal timestamps so the boundary (driven
        # by video) is known before the audio that straddles it.
        events.sort(key=lambda event: (event[0], event[1]))
        return [frame for _ts, _kind, frame in events]


@pytest.fixture
def media() -> MediaFactory:
    return MediaFactory()


@pytest.fixture
def make_segment(tmp_path: Path) -> Callable[..., Segment]:
    """Create a finalized-looking segment with a real (dummy) file."""

    def _make(segment_id: int, start_ns: int, end_ns: int) -> Segment:
        path = tmp_path / f"segment_{segment_id:06d}.mkv"
        path.write_bytes(b"segment")
        return Segment(
            id=segment_id,
            path=path,
            session_start_ns=start_ns,
            session_end_ns=end_ns,
            video_frames=120,
            audio_samples=96000,
        )

    return _make


@dataclass(frozen=True)
class SegmentProbe:
    """Facts read back from a written segment file."""

    path: Path
    video_codec: str
    width: int
    height: int
    pixel_format: str | None
    video_time_base: Fraction | None
    video_rate: Fraction | None
    video_packets: int
    first_video_pts: int | None
    keyframe_count: int
    decoded_video_frames: int
    audio_present: bool
    audio_codec: str | None
    audio_sample_rate: int | None
    audio_channels: int | None
    audio_time_base: Fraction | None
    audio_samples: int
    first_audio_pts: int | None


def probe_segment(path: Path) -> SegmentProbe:
    """Open *path* and read stream info, packet layout and decoded facts."""
    path = Path(path)
    with av.open(str(path)) as container:
        video = container.streams.video[0]
        audio_present = bool(container.streams.audio)

        video_packets = 0
        first_video_pts: int | None = None
        keyframe_count = 0
        for packet in container.demux():
            if packet.dts is None or packet.stream.type != "video":
                continue
            video_packets += 1
            if first_video_pts is None:
                first_video_pts = packet.pts
            if packet.is_keyframe:
                keyframe_count += 1

        video_codec = video.codec_context
        video_meta = (
            video_codec.name,
            video_codec.width,
            video_codec.height,
            video_codec.pix_fmt,
            video.time_base,
            video.average_rate,
        )

    with av.open(str(path)) as container:
        video = container.streams.video[0]
        decoded_video_frames = sum(1 for _ in container.decode(video))

    audio_codec: str | None = None
    audio_sample_rate: int | None = None
    audio_channels: int | None = None
    audio_time_base: Fraction | None = None
    audio_samples = 0
    first_audio_pts: int | None = None
    if audio_present:
        with av.open(str(path)) as container:
            audio_stream = container.streams.audio[0]
            codec_context = audio_stream.codec_context
            audio_codec = codec_context.name
            audio_sample_rate = codec_context.sample_rate
            audio_channels = codec_context.channels
            audio_time_base = audio_stream.time_base
            for frame in container.decode(audio_stream):
                if isinstance(frame, av.AudioFrame):
                    if first_audio_pts is None:
                        first_audio_pts = frame.pts
                    audio_samples += frame.samples

    codec, width, height, pix_fmt, time_base, rate = video_meta
    return SegmentProbe(
        path=path,
        video_codec=codec,
        width=width,
        height=height,
        pixel_format=pix_fmt,
        video_time_base=time_base,
        video_rate=rate,
        video_packets=video_packets,
        first_video_pts=first_video_pts,
        keyframe_count=keyframe_count,
        decoded_video_frames=decoded_video_frames,
        audio_present=audio_present,
        audio_codec=audio_codec,
        audio_sample_rate=audio_sample_rate,
        audio_channels=audio_channels,
        audio_time_base=audio_time_base,
        audio_samples=audio_samples,
        first_audio_pts=first_audio_pts,
    )


@pytest.fixture
def probe() -> Callable[[Path], SegmentProbe]:
    return probe_segment
