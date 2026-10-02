"""Stream-copy remux of finalized segments into a single replay MKV.

No decoding or encoding happens here.  Packets are copied from the source
segments and their timestamps are rebased onto one continuous replay timeline
that starts at zero.  Each segment already starts its own packets at ``0``, so
the builder adds the segment's timeline offset to every packet.

All timeline math uses :class:`~fractions.Fraction` and integers.  Float seconds
are never used as a source of truth.
"""

from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Protocol

import av
import av.audio.stream
import av.stream
import av.video.stream

from quickreplay.recording.models import Segment
from quickreplay.replay.errors import (
    ReplayAssetError,
    ReplayRemuxError,
    ReplaySegmentError,
    ReplayStreamMismatchError,
)
from quickreplay.units import NANOSECONDS_PER_SECOND, round_fraction


@dataclass(frozen=True, slots=True)
class VideoLayout:
    """Stream-copy relevant video properties of a segment."""

    codec: str
    width: int
    height: int
    pixel_format: str | None
    time_base: Fraction | None
    rate: Fraction | None
    extradata: bytes


@dataclass(frozen=True, slots=True)
class AudioLayout:
    """Stream-copy relevant audio properties of a segment."""

    codec: str
    sample_rate: int
    channels: int
    channel_layout: str | None
    time_base: Fraction | None
    extradata: bytes


@dataclass(frozen=True, slots=True)
class SegmentLayout:
    """The stream layout of one segment file."""

    video: VideoLayout
    audio: AudioLayout | None


class Remux(Protocol):
    """Remux *segments* into the (not yet published) file *tmp_path*."""

    def __call__(self, segments: tuple[Segment, ...], tmp_path: Path) -> None: ...


def probe_layout(path: Path) -> SegmentLayout:
    """Read the stream layout of a segment file without decoding it."""
    try:
        with av.open(str(path)) as container:
            if not container.streams.video:
                raise ReplaySegmentError(f"segment has no video stream: {path}")
            audio = None
            if container.streams.audio:
                audio = _audio_layout(container.streams.audio[0])
            return SegmentLayout(video=_video_layout(container.streams.video[0]), audio=audio)
    except ReplaySegmentError:
        raise
    except Exception as exc:  # noqa: BLE001 - wrap any PyAV/IO failure
        raise ReplaySegmentError(f"failed to read segment layout {path}: {exc}") from exc


def _video_layout(stream: av.video.stream.VideoStream) -> VideoLayout:
    codec = stream.codec_context
    return VideoLayout(
        codec=codec.name,
        width=codec.width,
        height=codec.height,
        pixel_format=codec.pix_fmt,
        time_base=stream.time_base,
        rate=stream.average_rate,
        extradata=bytes(codec.extradata or b""),
    )


def _audio_layout(stream: av.audio.stream.AudioStream) -> AudioLayout:
    codec = stream.codec_context
    layout = getattr(codec, "layout", None)
    return AudioLayout(
        codec=codec.name,
        sample_rate=codec.sample_rate,
        channels=codec.channels,
        channel_layout=getattr(layout, "name", None),
        time_base=stream.time_base,
        extradata=bytes(codec.extradata or b""),
    )


def validate_segment_layouts(segments: tuple[Segment, ...]) -> None:
    """Ensure every segment can be stream-copied into the same output streams."""
    reference = probe_layout(segments[0].path)
    for segment in segments[1:]:
        layout = probe_layout(segment.path)
        if layout != reference:
            raise ReplayStreamMismatchError(
                f"segment {segment.id} layout does not match the first segment: "
                f"{layout} != {reference}"
            )


def remux_segments(segments: tuple[Segment, ...], tmp_path: Path) -> None:
    """Stream-copy all *segments* into *tmp_path* as one continuous MKV."""
    if not segments:
        raise ReplayRemuxError("cannot remux an empty segment list")
    base_ns = segments[0].session_start_ns
    container = av.open(str(tmp_path), mode="w", format="matroska")
    try:
        output_streams: dict[str, av.stream.Stream] = {}
        last_ticks: dict[str, int] = {}
        for segment in segments:
            offset_ns = segment.session_start_ns - base_ns
            _mux_segment(container, output_streams, last_ticks, segment.path, offset_ns)
    except BaseException as exc:
        _close_quietly(container)
        if isinstance(exc, ReplayAssetError):
            raise
        raise ReplayRemuxError(f"failed to remux replay asset: {exc}") from exc
    try:
        container.close()
    except Exception as exc:  # noqa: BLE001 - wrap any PyAV/IO failure
        _close_quietly(container)
        raise ReplayRemuxError(f"failed to finalize replay container: {exc}") from exc


def _mux_segment(
    container: av.container.OutputContainer,
    output_streams: dict[str, av.stream.Stream],
    last_ticks: dict[str, int],
    path: Path,
    offset_ns: int,
) -> None:
    with av.open(str(path)) as source:
        for in_stream in source.streams:
            if in_stream.type not in output_streams:
                output_streams[in_stream.type] = container.add_stream_from_template(
                    in_stream, opaque=True
                )
        for packet in source.demux():
            if packet.dts is None and packet.pts is None:
                # PyAV yields one final packet without timestamps per demux().
                continue
            out_stream = output_streams[packet.stream.type]
            _rebase_packet(packet, out_stream, offset_ns)
            _check_forward(packet, last_ticks)
            container.mux(packet)


def _rebase_packet(packet: av.Packet, out_stream: av.stream.Stream, offset_ns: int) -> None:
    source_time_base = packet.time_base
    packet.stream = out_stream
    output_time_base = out_stream.time_base
    if output_time_base is None:
        raise ReplayRemuxError("replay output stream has no time base")
    if source_time_base is not None and source_time_base != output_time_base:
        packet.pts = _rescale(packet.pts, source_time_base, output_time_base)
        packet.dts = _rescale(packet.dts, source_time_base, output_time_base)
    offset_ticks = round_fraction(Fraction(offset_ns, NANOSECONDS_PER_SECOND) / output_time_base)
    if packet.pts is not None:
        packet.pts += offset_ticks
    if packet.dts is not None:
        packet.dts += offset_ticks


def _rescale(value: int | None, from_time_base: Fraction, to_time_base: Fraction) -> int | None:
    if value is None:
        return None
    return round_fraction(Fraction(value) * from_time_base / to_time_base)


def _check_forward(packet: av.Packet, last_ticks: dict[str, int]) -> None:
    stream_type = packet.stream.type
    timestamp = packet.dts if packet.dts is not None else packet.pts
    if timestamp is None:
        return
    previous = last_ticks.get(stream_type)
    if previous is not None and timestamp < previous:
        raise ReplayRemuxError(
            f"{stream_type} timestamp regressed across a segment boundary: {timestamp} < {previous}"
        )
    last_ticks[stream_type] = timestamp


def _close_quietly(container: av.container.OutputContainer) -> None:
    try:
        container.close()
    except Exception:  # noqa: BLE001 - best effort cleanup
        pass
