"""Events emitted by the recorder worker process.

Every event is an immutable, picklable value object safe to send over a
multiprocessing queue.  Events carry only plain data or other domain models;
never native objects or video/audio frames.
"""

from dataclasses import dataclass
from uuid import UUID

from quickreplay.input.models import InputDescriptor, StreamInfo
from quickreplay.recording.models import (
    RecordingMetrics,
    WorkerErrorCode,
    WorkerState,
)
from quickreplay.replay.models import ReplayAsset


@dataclass(frozen=True, slots=True)
class WorkerStateChanged:
    """The worker changed state."""

    state: WorkerState


@dataclass(frozen=True, slots=True)
class InputsDiscovered:
    """Result of an input discovery request."""

    request_id: UUID
    inputs: tuple[InputDescriptor, ...]


@dataclass(frozen=True, slots=True)
class StreamStarted:
    """The input stream has started and its format is known.

    ``request_id`` correlates the event with a ``ResumeRecording`` or
    ``ChangeInput`` command so a stale asynchronous response can be ignored.
    ``StartRecording`` leaves it ``None``.
    """

    stream_info: StreamInfo
    request_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class RecordingMetricsUpdated:
    """Periodic recording metrics update."""

    metrics: RecordingMetrics


@dataclass(frozen=True, slots=True)
class ReplayPrepared:
    """A replay asset is ready; the application may enter replay."""

    request_id: UUID
    asset: ReplayAsset


@dataclass(frozen=True, slots=True)
class WorkerError:
    """A worker error, identified by a machine-readable code."""

    code: WorkerErrorCode
    message: str
    request_id: UUID | None = None


type WorkerEvent = (
    WorkerStateChanged
    | InputsDiscovered
    | StreamStarted
    | RecordingMetricsUpdated
    | ReplayPrepared
    | WorkerError
)
