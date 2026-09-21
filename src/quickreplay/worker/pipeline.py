"""Recording pipeline: capture thread + encode thread.

The capture thread owns the :class:`~quickreplay.input.source.InputSource`.
The encode thread owns the
:class:`~quickreplay.recording.segment_recorder.SegmentRecorder` and the
:class:`~quickreplay.recording.ring_storage.RingStorage`.  Frames travel
between them through bounded in-process queues only.
"""

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from uuid import uuid4

from quickreplay.input.models import AudioFrame, CaptureItem, InputConfig, StreamInfo, VideoFrame
from quickreplay.input.source import InputSource
from quickreplay.recording.models import RecordingMetrics, RecordingSession, Segment
from quickreplay.recording.ring_storage import RingStorage
from quickreplay.recording.segment_recorder import SegmentRecorder
from quickreplay.worker.errors import (
    PipelineFormatChangeError,
    PipelineOrderingError,
    PipelineShutdownError,
    PipelineStartupError,
)
from quickreplay.worker.frame_queues import FrameQueues
from quickreplay.worker.inputs import InputSourceHandle, open_input_source
from quickreplay.worker.settings import RecorderWorkerSettings

CLOCK = time.perf_counter_ns
"""Monotonic control clock; never used as a media timestamp."""

_IDLE_SLEEP_SECONDS = 0.001
_WAIT_SLICE_SECONDS = 0.02


@dataclass(slots=True)
class _MetricsState:
    captured_video_frames: int = 0
    recorded_video_frames: int = 0
    captured_audio_samples: int = 0
    recorded_audio_samples: int = 0
    segment_count: int = 0
    buffer_duration_ns: int = 0


class RecordingPipeline:
    """Runs one recording session across a capture and an encode thread."""

    def __init__(
        self,
        settings: RecorderWorkerSettings,
        *,
        input_factory: Callable[[InputConfig], InputSourceHandle] = open_input_source,
        clock: Callable[[], int] = CLOCK,
    ) -> None:
        self._settings = settings
        self._input_factory = input_factory
        self._clock = clock

        self._source: InputSource | None = None
        self._queues: FrameQueues | None = None
        self._capture_thread: threading.Thread | None = None
        self._encode_thread: threading.Thread | None = None

        self._stop_event = threading.Event()
        self._format_ready = threading.Event()
        self._session_ready = threading.Event()

        self._stream_info: StreamInfo | None = None
        self._first_video_ts: int | None = None
        self._session: RecordingSession | None = None
        self._ring: RingStorage | None = None

        self._fatal: BaseException | None = None
        self._active = False

        self._metrics = _MetricsState()
        self._metrics_lock = threading.Lock()
        self._last_metrics_ns: int | None = None
        self._last_captured_video = 0
        self._last_recorded_video = 0

    # -- queries -----------------------------------------------------------
    @property
    def is_active(self) -> bool:
        return self._active

    @property
    def stream_info(self) -> StreamInfo | None:
        return self._stream_info

    @property
    def session(self) -> RecordingSession | None:
        return self._session

    @property
    def ring(self) -> RingStorage | None:
        return self._ring

    def poll_fatal(self) -> BaseException | None:
        """The first fatal failure seen by either thread, if any."""
        return self._fatal

    def take_ring(self) -> RingStorage | None:
        """Relinquish ownership of the ring buffer to the caller."""
        ring = self._ring
        self._ring = None
        return ring

    # -- lifecycle ---------------------------------------------------------
    def start(self, config: InputConfig) -> StreamInfo:
        """Open the input and start both threads.  Blocks until format is known."""
        if self._active:
            raise PipelineStartupError("the pipeline is already active")
        settings = self._settings
        settings.buffer_root.mkdir(parents=True, exist_ok=True)

        handle = self._input_factory(config)
        self._source = handle.source
        self._queues = FrameQueues(
            video_capacity=settings.video_queue_capacity,
            audio_capacity=settings.audio_queue_capacity,
        )
        self._capture_thread = threading.Thread(
            target=self._capture_loop,
            args=(handle.supports_audio,),
            name="qr-capture",
            daemon=True,
        )
        self._capture_thread.start()

        try:
            if not self._format_ready.wait(timeout=settings.stream_start_timeout_seconds):
                raise PipelineStartupError("timed out waiting for the first video frame")
            if self._fatal is not None:
                raise self._fatal
            info = self._stream_info
            first_video_ts = self._first_video_ts
            if info is None or first_video_ts is None:
                raise PipelineStartupError("the input did not provide a video frame")

            session_id = uuid4()
            directory = settings.buffer_root / str(session_id)
            directory.mkdir(parents=True, exist_ok=True)
            session = RecordingSession(session_id, info, first_video_ts, directory)
            ring = RingStorage(buffer_duration_ns=settings.buffer_duration_ns)
            recorder = SegmentRecorder(segment_duration_ns=settings.segment_duration_ns)
            recorder.start(session)

            self._session = session
            self._ring = ring
            self._encode_thread = threading.Thread(
                target=self._encode_loop,
                args=(recorder, ring, info.audio is not None),
                name="qr-encode",
                daemon=True,
            )
            self._encode_thread.start()
            self._session_ready.set()
            self._active = True
            self._last_metrics_ns = self._clock()
            return info
        except BaseException:
            self._active = False
            self.abort()
            raise

    def stop(self) -> None:
        """Stop capture, drain the queues, finalize and stop encoding."""
        if self._source is None and self._capture_thread is None:
            return
        self._stop_event.set()
        self._join_capture()
        queues = self._queues
        if queues is not None:
            queues.begin_drain()
        self._join_encode()
        self._active = False

    def abort(self) -> None:
        """Best-effort stop used on failure paths.  Never raises."""
        self._stop_event.set()
        try:
            self._join_capture()
        except Exception:  # noqa: BLE001 - best effort
            pass
        queues = self._queues
        if queues is not None:
            try:
                queues.begin_drain()
            except Exception:  # noqa: BLE001 - best effort
                pass
        try:
            self._join_encode()
        except Exception:  # noqa: BLE001 - best effort
            pass
        self._active = False

    # -- metrics -----------------------------------------------------------
    def metrics(self) -> RecordingMetrics:
        """Current recording metrics; fps values are measured, not declared."""
        now = self._clock()
        with self._metrics_lock:
            captured_video = self._metrics.captured_video_frames
            recorded_video = self._metrics.recorded_video_frames
            captured_audio = self._metrics.captured_audio_samples
            recorded_audio = self._metrics.recorded_audio_samples
            segment_count = self._metrics.segment_count
            buffer_duration_ns = self._metrics.buffer_duration_ns

        input_fps = 0.0
        recording_fps = 0.0
        if self._last_metrics_ns is not None and now > self._last_metrics_ns:
            elapsed_seconds = (now - self._last_metrics_ns) / 1_000_000_000
            input_fps = (captured_video - self._last_captured_video) / elapsed_seconds
            recording_fps = (recorded_video - self._last_recorded_video) / elapsed_seconds
        self._last_metrics_ns = now
        self._last_captured_video = captured_video
        self._last_recorded_video = recorded_video

        video_drops, audio_drops = self._queues.drop_counts() if self._queues else (0, 0)
        return RecordingMetrics(
            captured_video_frames=captured_video,
            recorded_video_frames=recorded_video,
            captured_audio_samples=captured_audio,
            recorded_audio_samples=recorded_audio,
            video_queue_drops=video_drops,
            audio_queue_drops=audio_drops,
            buffer_duration_ns=buffer_duration_ns,
            segment_count=segment_count,
            input_fps=input_fps,
            recording_fps=recording_fps,
        )

    # -- capture thread ----------------------------------------------------
    def _capture_loop(self, supports_audio: bool) -> None:
        source = self._source
        queues = self._queues
        if source is None or queues is None:  # pragma: no cover - defensive
            return
        buffer: list[CaptureItem] = []
        forwarding = False
        first_video_ts: int | None = None
        control_start = self._clock()
        try:
            source.open()
            while not self._stop_event.is_set():
                if (
                    self._stream_info is None
                    and self._clock() - control_start >= self._settings.stream_start_timeout_ns
                ):
                    raise PipelineStartupError("timed out waiting for the first video frame")
                item = source.read()
                if item is None:
                    time.sleep(_IDLE_SLEEP_SECONDS)
                    continue
                if not forwarding:
                    buffer.append(item)
                    if isinstance(item, VideoFrame):
                        if first_video_ts is None:
                            first_video_ts = item.timestamp_ns
                        if self._bootstrap_complete(item, first_video_ts, supports_audio):
                            info = source.stream_info
                            if info is None:
                                raise PipelineStartupError("the input did not report stream info")
                            self._stream_info = info
                            self._first_video_ts = first_video_ts
                            self._format_ready.set()
                    if self._format_ready.is_set() and self._session_ready.wait(timeout=0.01):
                        forwarding = True
                        for buffered in buffer:
                            self._forward(buffered, first_video_ts, queues)
                        buffer.clear()
                    continue
                self._forward(item, first_video_ts, queues)
        except BaseException as exc:  # noqa: BLE001 - reported through poll_fatal
            self._set_fatal(exc)
        finally:
            try:
                source.close()
            except Exception:  # noqa: BLE001 - best effort
                pass
            self._format_ready.set()

    def _bootstrap_complete(
        self, frame: VideoFrame, first_video_ts: int, supports_audio: bool
    ) -> bool:
        if self._stream_info is not None:
            return True
        if not supports_audio:
            return True
        source = self._source
        info = source.stream_info if source is not None else None
        if info is not None and info.audio is not None:
            return True
        return frame.timestamp_ns - first_video_ts >= self._settings.stream_probe_window_ns

    def _forward(self, item: CaptureItem, first_video_ts: int | None, queues: FrameQueues) -> None:
        if isinstance(item, VideoFrame):
            self._increment("captured_video_frames", 1)
            queues.put_video(item)
            return
        if not isinstance(item, AudioFrame):  # pragma: no cover - defensive
            return
        if first_video_ts is not None and item.timestamp_ns < first_video_ts:
            return  # audio before the session epoch
        if self._stream_info is not None and self._stream_info.audio is None:
            raise PipelineFormatChangeError(
                "audio arrived after the session was fixed as video-only"
            )
        self._increment("captured_audio_samples", item.sample_count)
        queues.put_audio(item)

    # -- encode thread -----------------------------------------------------
    def _encode_loop(
        self, recorder: SegmentRecorder, ring: RingStorage, expect_audio: bool
    ) -> None:
        queues = self._queues
        if queues is None:  # pragma: no cover - defensive
            return
        last_ts: int | None = None
        try:
            while True:
                item = queues.take_next(
                    holdback_ns=self._settings.av_reorder_holdback_ns, expect_audio=expect_audio
                )
                if item is None:
                    if queues.draining and queues.empty():
                        break
                    queues.wait(_WAIT_SLICE_SECONDS)
                    continue
                if last_ts is not None and item.timestamp_ns < last_ts:
                    raise PipelineOrderingError(
                        f"frame timestamp {item.timestamp_ns} is older than the "
                        f"last encoded {last_ts}"
                    )
                self._encode_item(recorder, ring, item)
                last_ts = item.timestamp_ns
        except BaseException as exc:  # noqa: BLE001 - reported through poll_fatal
            self._set_fatal(exc)
        finally:
            try:
                final = recorder.finish()
                if final is not None:
                    self._add_segment(ring, final)
            except BaseException as exc:  # noqa: BLE001 - reported through poll_fatal
                self._set_fatal(exc)
            finally:
                recorder.close()

    def _encode_item(self, recorder: SegmentRecorder, ring: RingStorage, item: CaptureItem) -> None:
        if isinstance(item, VideoFrame):
            for segment in recorder.push_video(item):
                self._add_segment(ring, segment)
            self._increment("recorded_video_frames", 1)
            return
        recorder.push_audio(item)
        self._increment("recorded_audio_samples", item.sample_count)

    def _add_segment(self, ring: RingStorage, segment: Segment) -> None:
        ring.add(segment)
        with self._metrics_lock:
            self._metrics.segment_count = ring.segment_count
            self._metrics.buffer_duration_ns = ring.duration_ns

    # -- helpers -----------------------------------------------------------
    def _join_capture(self) -> None:
        thread = self._capture_thread
        if thread is None:
            return
        grace = self._settings.freeze_grace_seconds
        thread.join(timeout=grace)
        if thread.is_alive():
            source = self._source
            if source is not None:
                try:
                    source.close()
                except Exception:  # noqa: BLE001 - best effort interrupt
                    pass
            thread.join(timeout=grace)
        if thread.is_alive():
            raise PipelineShutdownError("the capture thread did not stop")
        self._capture_thread = None

    def _join_encode(self) -> None:
        thread = self._encode_thread
        if thread is None:
            return
        thread.join(timeout=self._settings.drain_timeout_seconds)
        if thread.is_alive():
            raise PipelineShutdownError("the encode thread did not stop")
        self._encode_thread = None

    def _set_fatal(self, exc: BaseException) -> None:
        if self._fatal is None:
            self._fatal = exc

    def _increment(self, field: str, amount: int) -> None:
        with self._metrics_lock:
            setattr(self._metrics, field, getattr(self._metrics, field) + amount)
