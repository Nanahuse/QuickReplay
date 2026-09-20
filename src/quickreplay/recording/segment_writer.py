"""Encode and mux a single MKV segment with PyAV.

A :class:`SegmentWriter` owns exactly one segment (one container and a fresh
encoder per stream).  Encoders and containers are never reused across
segments, which keeps every segment independently decodable.

The writer publishes its output atomically: it encodes into
``segment_000000.tmp.mkv`` and only replaces it with ``segment_000000.mkv``
after the container has closed cleanly.  A failed writer removes its temporary
file and never exposes a partial segment.
"""

import os
from fractions import Fraction
from pathlib import Path
from typing import Protocol

import av
import numpy as np

from quickreplay.input.models import StreamInfo, VideoFrame
from quickreplay.recording.errors import (
    SegmentEncodingError,
    SegmentMuxError,
    SegmentRecorderError,
)
from quickreplay.recording.frame_converter import FrameConverter


class SegmentWriterLike(Protocol):
    """Protocol implemented by :class:`SegmentWriter` (and test doubles)."""

    def write_video(self, frame: VideoFrame, pts: int) -> None: ...

    def write_audio(self, data: np.ndarray, pts: int) -> None: ...

    def finalize(self) -> Path: ...

    def abort(self) -> None: ...


class SegmentWriter:
    """Write one segment file."""

    def __init__(
        self,
        segment_id: int,
        directory: Path,
        stream_info: StreamInfo,
        *,
        converter: FrameConverter | None = None,
    ) -> None:
        self.segment_id = segment_id
        self.directory = Path(directory)
        self.stream_info = stream_info
        self._converter = converter or FrameConverter()

        self._final_path = self.directory / f"segment_{segment_id:06d}.mkv"
        self._tmp_path = self.directory / f"segment_{segment_id:06d}.tmp.mkv"

        self._finalized = False
        self._aborted = False
        self._first_video = True

        video = stream_info.video
        self._video_time_base = Fraction(video.fps.denominator, video.fps.numerator)
        self._audio_time_base: Fraction | None = None

        self._container = av.open(str(self._tmp_path), mode="w", format="matroska")

        video_stream = self._container.add_stream("libx264", rate=video.fps)
        video_stream.width = video.width
        video_stream.height = video.height
        video_stream.pix_fmt = "yuv420p"
        video_stream.time_base = self._video_time_base
        gop = max(1, round(float(video.fps) * 2))
        video_stream.options = {
            "preset": "veryfast",
            "tune": "zerolatency",
            "crf": "20",
            "g": str(gop),
            "keyint_min": "1",
            "sc_threshold": "0",
            "forced-idr": "1",
        }
        self._video_stream = video_stream

        audio = stream_info.audio
        self._audio_stream: av.AudioStream | None = None
        if audio is not None:
            if audio.channels not in (1, 2):
                self._abort_files()
                raise SegmentEncodingError(
                    f"unsupported channel count {audio.channels}; only mono/stereo are supported"
                )
            audio_stream = self._container.add_stream("pcm_f32le", rate=audio.sample_rate)
            audio_stream.layout = "mono" if audio.channels == 1 else "stereo"
            audio_stream.time_base = Fraction(1, audio.sample_rate)
            self._audio_time_base = Fraction(1, audio.sample_rate)
            self._audio_stream = audio_stream

    # -- properties --------------------------------------------------------
    @property
    def tmp_path(self) -> Path:
        return self._tmp_path

    @property
    def final_path(self) -> Path:
        return self._final_path

    # -- data --------------------------------------------------------------
    def write_video(self, frame: VideoFrame, pts: int) -> None:
        if self._finalized or self._aborted:
            raise SegmentEncodingError("writer is closed")
        try:
            av_frame = self._converter.to_av_video(frame)
            av_frame.pts = pts
            av_frame.time_base = self._video_time_base
            if self._first_video:
                # Force the first frame of the segment to be an IDR keyframe.
                av_frame.pict_type = av.video.frame.PictureType.I
                self._first_video = False
            for packet in self._video_stream.encode(av_frame):
                self._container.mux(packet)
        except SegmentRecorderError:
            self.abort()
            raise
        except Exception as exc:  # noqa: BLE001 - wrap any PyAV failure
            self.abort()
            raise SegmentEncodingError(f"video encode failed: {exc}") from exc

    def write_audio(self, data: np.ndarray, pts: int) -> None:
        if self._finalized or self._aborted:
            raise SegmentEncodingError("writer is closed")
        if self._audio_stream is None:
            raise SegmentEncodingError("segment has no audio stream")
        try:
            audio = self.stream_info.audio
            assert audio is not None
            av_frame = self._converter.to_av_audio(data, audio.sample_rate, audio.channels)
            av_frame.pts = pts
            av_frame.time_base = self._audio_time_base
            for packet in self._audio_stream.encode(av_frame):
                self._container.mux(packet)
        except SegmentRecorderError:
            self.abort()
            raise
        except Exception as exc:  # noqa: BLE001 - wrap any PyAV failure
            self.abort()
            raise SegmentEncodingError(f"audio encode failed: {exc}") from exc

    # -- lifecycle ---------------------------------------------------------
    def finalize(self) -> Path:
        """Flush, close and atomically publish the segment file."""
        if self._finalized:
            return self._final_path
        if self._aborted:
            raise SegmentMuxError("writer was aborted")
        try:
            for packet in self._video_stream.encode(None):
                self._container.mux(packet)
            if self._audio_stream is not None:
                for packet in self._audio_stream.encode(None):
                    self._container.mux(packet)
            self._container.close()
        except Exception as exc:  # noqa: BLE001 - wrap any PyAV failure
            self._abort_files()
            raise SegmentMuxError(f"segment finalize failed: {exc}") from exc

        try:
            os.replace(self._tmp_path, self._final_path)
        except OSError as exc:
            self._abort_files()
            raise SegmentMuxError(f"segment publish failed: {exc}") from exc
        self._finalized = True
        return self._final_path

    def abort(self) -> None:
        """Best-effort cleanup of an unfinished segment."""
        if self._finalized or self._aborted:
            return
        self._aborted = True
        self._abort_files()

    def _abort_files(self) -> None:
        try:
            self._container.close()
        except Exception:  # noqa: BLE001 - best effort
            pass
        try:
            if self._tmp_path.exists():
                self._tmp_path.unlink()
        except OSError:
            pass
