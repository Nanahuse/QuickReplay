"""Recording domain models: segments, sessions, metrics and worker state."""

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from uuid import UUID

from quickreplay.input.models import StreamInfo


@dataclass(frozen=True, slots=True)
class Segment:
    """Metadata of one finalised segment file.

    ``duration_ns`` is derived from the session range rather than stored, so it
    cannot drift from the start/end fields.
    """

    id: int
    path: Path

    session_start_ns: int
    session_end_ns: int

    video_frames: int
    audio_samples: int

    def __post_init__(self) -> None:
        if self.session_end_ns < self.session_start_ns:
            raise ValueError(
                "session_end_ns must be >= session_start_ns "
                f"({self.session_end_ns} < {self.session_start_ns})"
            )
        if self.video_frames < 0:
            raise ValueError(f"video_frames must not be negative, got {self.video_frames}")
        if self.audio_samples < 0:
            raise ValueError(f"audio_samples must not be negative, got {self.audio_samples}")

    @property
    def duration_ns(self) -> int:
        """Segment duration in nanoseconds."""
        return self.session_end_ns - self.session_start_ns


@dataclass(frozen=True, slots=True)
class RecordingSession:
    """One continuous recording session.

    Resuming recording after a replay creates a new session rather than
    extending this one.  The lifecycle itself is not implemented yet.
    """

    id: UUID
    stream_info: StreamInfo
    epoch_ns: int
    directory: Path


@dataclass(frozen=True, slots=True)
class RecordingMetrics:
    """Measured recording metrics, suitable for display.

    ``input_fps`` / ``recording_fps`` are measured values for the UI.  They are
    distinct from the declared stream FPS (which is a :class:`~fractions.Fraction`
    in :class:`~quickreplay.input.models.StreamInfo`).
    """

    captured_video_frames: int
    recorded_video_frames: int

    captured_audio_samples: int
    recorded_audio_samples: int

    video_queue_drops: int
    audio_queue_drops: int

    buffer_duration_ns: int
    segment_count: int

    input_fps: float
    recording_fps: float

    def __post_init__(self) -> None:
        for name in (
            "captured_video_frames",
            "recorded_video_frames",
            "captured_audio_samples",
            "recorded_audio_samples",
            "video_queue_drops",
            "audio_queue_drops",
            "buffer_duration_ns",
            "segment_count",
        ):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must not be negative, got {getattr(self, name)}")
        if self.input_fps < 0:
            raise ValueError(f"input_fps must not be negative, got {self.input_fps}")
        if self.recording_fps < 0:
            raise ValueError(f"recording_fps must not be negative, got {self.recording_fps}")


class WorkerState(StrEnum):
    """Internal state of the recorder worker process."""

    IDLE = "idle"
    STARTING = "starting"
    RECORDING = "recording"
    FREEZING = "freezing"
    FROZEN = "frozen"
    STOPPING = "stopping"
    ERROR = "error"
    SHUTTING_DOWN = "shutting_down"


class WorkerErrorCode(StrEnum):
    """Machine-readable worker error codes."""

    INPUT_NOT_FOUND = "input_not_found"
    INPUT_OPEN_FAILED = "input_open_failed"
    INPUT_DISCONNECTED = "input_disconnected"

    UNSUPPORTED_FORMAT = "unsupported_format"

    CAPTURE_FAILED = "capture_failed"
    ENCODER_FAILED = "encoder_failed"
    MUXER_FAILED = "muxer_failed"

    REPLAY_ASSET_FAILED = "replay_asset_failed"

    DISK_FULL = "disk_full"
    FILE_IO_ERROR = "file_io_error"

    INTERNAL_ERROR = "internal_error"
