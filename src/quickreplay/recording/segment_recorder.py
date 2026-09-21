"""Rotation and lifecycle for short MKV segments.

:class:`SegmentRecorder` consumes domain :class:`~quickreplay.input.models.VideoFrame`
/ :class:`~quickreplay.input.models.AudioFrame` values in a single-threaded
owner and produces finalised :class:`~quickreplay.recording.models.Segment`
files.  It does not own a thread; it is meant to run on the encoder side of a
future capture queue.

Segment boundaries are driven by **video timestamps**: the first video frame
whose session time reaches ``segment_start + segment_duration`` starts the next
segment.  Audio never drives rotation; audio frames that straddle a boundary
are split at sample precision once the boundary is known, and a small amount of
audio ahead of the video boundary is held pending.
"""

from collections.abc import Callable
from fractions import Fraction
from pathlib import Path

import numpy as np

from quickreplay.input.models import AudioFrame, StreamInfo, VideoFrame
from quickreplay.recording.errors import (
    SegmentEncodingError,
    SegmentFormatError,
    SegmentRecorderError,
    SegmentTimestampError,
)
from quickreplay.recording.models import RecordingSession, Segment
from quickreplay.recording.segment_writer import SegmentWriter, SegmentWriterLike
from quickreplay.units import NANOSECONDS_PER_SECOND, round_fraction

DEFAULT_SEGMENT_DURATION_NS = 2_000_000_000
"""Default segment duration: two seconds."""

WriterFactory = Callable[[int, Path, StreamInfo], SegmentWriterLike]


def _default_writer_factory(
    segment_id: int, directory: Path, stream_info: StreamInfo
) -> SegmentWriterLike:
    return SegmentWriter(segment_id, directory, stream_info)


class SegmentRecorder:
    """Split a continuous frame stream into independently decodable segments."""

    def __init__(
        self,
        *,
        segment_duration_ns: int = DEFAULT_SEGMENT_DURATION_NS,
        writer_factory: WriterFactory | None = None,
    ) -> None:
        if segment_duration_ns <= 0:
            raise ValueError(f"segment_duration_ns must be positive, got {segment_duration_ns}")
        self._segment_duration_ns = segment_duration_ns
        self._writer_factory: WriterFactory = writer_factory or _default_writer_factory

        self._session: RecordingSession | None = None
        self._stream_info: StreamInfo | None = None
        self._epoch_ns: int | None = None
        self._fps: Fraction | None = None
        self._sample_rate: int | None = None
        self._channels: int | None = None

        self._current_writer: SegmentWriterLike | None = None
        self._current_id = 0
        self._segment_start_ns: int | None = None
        self._segment_video_frames = 0
        self._segment_audio_samples = 0
        self._last_video_pts = -1

        self._last_video_session_ns: int | None = None
        self._last_audio_session_ns: int | None = None
        # End of the accepted audio sample timeline for the whole session.
        # This intentionally survives segment rotation.
        self._accepted_audio_end_sample: int | None = None
        # Buffered audio chunks: (start_sample, float32 planar data).
        self._audio_chunks: list[tuple[int, np.ndarray]] = []

        self._finished = False
        self._closed = False

    # -- lifecycle ---------------------------------------------------------
    def start(self, session: RecordingSession) -> None:
        """Begin a recording session."""
        if self._session is not None:
            raise SegmentRecorderError("recorder has already been started")
        if self._closed:
            raise SegmentRecorderError("recorder has been closed")
        self._session = session
        self._stream_info = session.stream_info
        self._epoch_ns = session.epoch_ns
        self._fps = session.stream_info.video.fps
        audio = session.stream_info.audio
        if audio is not None:
            self._sample_rate = audio.sample_rate
            self._channels = audio.channels
            self._accepted_audio_end_sample = None

    def push_video(self, frame: VideoFrame) -> tuple[Segment, ...]:
        """Feed a video frame, returning any segment finalized by rotation."""
        self._require_active()
        epoch_ns = self._epoch_ns
        assert epoch_ns is not None
        assert self._stream_info is not None
        self._validate_video_format(frame)
        self._validate_epoch(frame.timestamp_ns)
        session_ns = frame.timestamp_ns - epoch_ns

        if self._last_video_session_ns is not None and session_ns < self._last_video_session_ns:
            raise SegmentTimestampError(
                f"video timestamp regressed: {session_ns} < {self._last_video_session_ns}"
            )

        finalized: list[Segment] = []
        if self._current_writer is None:
            self._begin_segment(session_ns, drop_audio_before_ns=session_ns)
        else:
            assert self._segment_start_ns is not None
            threshold_ns = self._segment_start_ns + self._segment_duration_ns
            if session_ns >= threshold_ns:
                finalized.append(self._end_segment(session_ns))
                self._begin_segment(session_ns, drop_audio_before_ns=None)

        assert self._segment_start_ns is not None
        position = self._video_position(session_ns)
        pts = position - self._video_position(self._segment_start_ns)
        if pts > self._last_video_pts:
            writer = self._current_writer
            assert writer is not None
            writer.write_video(frame, pts)
            self._segment_video_frames += 1
            self._last_video_pts = pts
        # A duplicate CFR slot (equal position) is dropped to keep PTS
        # strictly increasing.

        self._last_video_session_ns = session_ns
        return tuple(finalized)

    def push_audio(self, frame: AudioFrame) -> int:
        """Feed an audio frame and return the number of accepted samples."""
        self._require_active()
        epoch_ns = self._epoch_ns
        assert epoch_ns is not None
        assert self._stream_info is not None
        if self._stream_info.audio is None:
            raise SegmentFormatError("the recording session has no audio stream")
        self._validate_audio_format(frame)
        self._validate_epoch(frame.timestamp_ns)

        session_ns = frame.timestamp_ns - epoch_ns
        if self._last_audio_session_ns is not None and session_ns < self._last_audio_session_ns:
            raise SegmentTimestampError(
                f"audio timestamp regressed: {session_ns} < {self._last_audio_session_ns}"
            )
        self._last_audio_session_ns = session_ns

        data = frame.data
        if not isinstance(data, np.ndarray):
            raise SegmentFormatError("AudioFrame.data must be a numpy.ndarray")
        if data.ndim != 2 or data.shape[0] != self._channels or data.shape[1] != frame.sample_count:
            raise SegmentFormatError(
                f"AudioFrame.data shape {data.shape} does not match "
                f"({self._channels}, {frame.sample_count})"
            )
        start_sample = self._sample_position(session_ns)
        end_sample = start_sample + frame.sample_count
        accepted_start = start_sample
        accepted_data = np.ascontiguousarray(data, dtype=np.float32)
        accepted_end = self._accepted_audio_end_sample
        if accepted_end is not None:
            if end_sample <= accepted_end:
                return 0
            if start_sample < accepted_end:
                overlap = accepted_end - start_sample
                accepted_start = accepted_end
                accepted_data = accepted_data[:, overlap:]

        accepted_samples = int(accepted_data.shape[1])
        if accepted_samples == 0:
            return 0
        self._accepted_audio_end_sample = accepted_start + accepted_samples
        self._audio_chunks.append((accepted_start, accepted_data))

        if self._current_writer is not None:
            # Audio before the current last video frame is definitely part of
            # this segment.  Audio after it is held until the next video frame
            # fixes the boundary (or until finish trims it).
            assert self._last_video_session_ns is not None
            self._flush_audio_until(self._last_video_session_ns)
        return accepted_samples

    def finish(self) -> Segment | None:
        """Finalize the last segment and return it (or ``None`` if no video)."""
        self._require_started()
        if self._finished:
            return None
        self._finished = True

        if self._current_writer is None or self._segment_video_frames == 0:
            if self._current_writer is not None:
                self._current_writer.abort()
                self._current_writer = None
            self._audio_chunks.clear()
            return None

        assert self._last_video_session_ns is not None
        fps = self._fps
        assert fps is not None
        frame_duration_ns = Fraction(NANOSECONDS_PER_SECOND, 1) / fps
        final_end_ns = round_fraction(Fraction(self._last_video_session_ns, 1) + frame_duration_ns)
        segment = self._end_segment(final_end_ns)
        self._audio_chunks.clear()  # trim trailing audio beyond the final video
        return segment

    def close(self) -> None:
        """Abort any unfinished segment.  Safe to call multiple times."""
        if self._closed:
            return
        self._closed = True
        if self._current_writer is not None:
            self._current_writer.abort()
            self._current_writer = None
        self._audio_chunks.clear()

    # -- segment lifecycle -------------------------------------------------
    def _begin_segment(self, start_ns: int, *, drop_audio_before_ns: int | None) -> None:
        if drop_audio_before_ns is not None:
            self._drop_audio_before(drop_audio_before_ns)
        assert self._session is not None and self._stream_info is not None
        self._current_writer = self._writer_factory(
            self._current_id, self._session.directory, self._stream_info
        )
        self._segment_start_ns = start_ns
        self._segment_video_frames = 0
        self._segment_audio_samples = 0
        self._last_video_pts = -1

    def _end_segment(self, boundary_ns: int) -> Segment:
        assert self._current_writer is not None and self._segment_start_ns is not None
        self._flush_audio_until(boundary_ns)
        writer = self._current_writer
        try:
            path = writer.finalize()
        except SegmentRecorderError:
            writer.abort()
            raise
        except Exception as exc:  # noqa: BLE001 - wrap unexpected writer failures
            writer.abort()
            raise SegmentEncodingError(f"segment finalize failed: {exc}") from exc

        segment = Segment(
            id=self._current_id,
            path=path,
            session_start_ns=self._segment_start_ns,
            session_end_ns=boundary_ns,
            video_frames=self._segment_video_frames,
            audio_samples=self._segment_audio_samples,
        )
        self._current_id += 1
        self._current_writer = None
        self._segment_start_ns = None
        self._segment_video_frames = 0
        self._segment_audio_samples = 0
        return segment

    # -- audio routing -----------------------------------------------------
    def _drop_audio_before(self, limit_ns: int) -> None:
        if self._sample_rate is None:
            return
        limit_sample = self._sample_position(limit_ns)
        while self._audio_chunks:
            start_sample, data = self._audio_chunks[0]
            length = int(data.shape[1])
            if start_sample >= limit_sample:
                break
            if start_sample + length <= limit_sample:
                self._audio_chunks.pop(0)
            else:
                take = limit_sample - start_sample
                self._audio_chunks[0] = (limit_sample, data[:, take:])
                break

    def _flush_audio_until(self, limit_ns: int) -> None:
        if self._current_writer is None or self._sample_rate is None:
            return
        limit_sample = self._sample_position(limit_ns)
        while self._audio_chunks:
            start_sample, data = self._audio_chunks[0]
            length = int(data.shape[1])
            if start_sample >= limit_sample:
                break
            if start_sample + length <= limit_sample:
                self._write_audio_chunk(start_sample, data)
                self._audio_chunks.pop(0)
            else:
                take = limit_sample - start_sample
                self._write_audio_chunk(start_sample, data[:, :take])
                self._audio_chunks[0] = (limit_sample, data[:, take:])
                break

    def _write_audio_chunk(self, start_sample: int, data: np.ndarray) -> None:
        if self._current_writer is None or data.shape[1] == 0:
            return
        assert self._segment_start_ns is not None
        pts = start_sample - self._sample_position(self._segment_start_ns)
        if pts < 0:
            raise SegmentTimestampError(
                "audio sample precedes the current segment start; "
                "out-of-order audio is not supported"
            )
        self._current_writer.write_audio(np.ascontiguousarray(data, dtype=np.float32), pts)
        self._segment_audio_samples += int(data.shape[1])

    # -- validation / math -------------------------------------------------
    def _require_started(self) -> None:
        if self._session is None:
            raise SegmentRecorderError("recorder has not been started")

    def _require_active(self) -> None:
        self._require_started()
        if self._closed:
            raise SegmentRecorderError("recorder has been closed")
        if self._finished:
            raise SegmentRecorderError("recorder has been finished")

    def _validate_epoch(self, timestamp_ns: int) -> None:
        assert self._epoch_ns is not None
        if timestamp_ns < self._epoch_ns:
            raise SegmentTimestampError(
                f"frame timestamp {timestamp_ns} precedes session epoch {self._epoch_ns}"
            )

    def _validate_video_format(self, frame: VideoFrame) -> None:
        assert self._stream_info is not None
        expected = self._stream_info.video
        actual = (frame.width, frame.height, frame.fps, frame.pixel_format.upper())
        wanted = (expected.width, expected.height, expected.fps, expected.pixel_format.upper())
        if actual != wanted:
            raise SegmentFormatError(f"video frame format {actual} does not match session {wanted}")

    def _validate_audio_format(self, frame: AudioFrame) -> None:
        assert self._stream_info is not None and self._stream_info.audio is not None
        expected = self._stream_info.audio
        if (frame.sample_rate, frame.channels) != (expected.sample_rate, expected.channels):
            raise SegmentFormatError(
                f"audio frame format {(frame.sample_rate, frame.channels)} does not match "
                f"session {(expected.sample_rate, expected.channels)}"
            )

    def _video_position(self, session_ns: int) -> int:
        assert self._fps is not None
        return round_fraction(Fraction(session_ns, NANOSECONDS_PER_SECOND) * self._fps)

    def _sample_position(self, session_ns: int) -> int:
        assert self._sample_rate is not None
        return round_fraction(Fraction(session_ns, NANOSECONDS_PER_SECOND) * self._sample_rate)
