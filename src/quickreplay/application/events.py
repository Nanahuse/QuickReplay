"""UI-independent events emitted by the application controller.

The worker protocol (``WorkerStateChanged`` / ``WorkerError`` / ``ReplayPrepared``)
is never exposed directly; it is translated into these application events.
"""

from dataclasses import dataclass
from uuid import UUID

from quickreplay.app.state import ApplicationState
from quickreplay.input.models import InputDescriptor, StreamInfo
from quickreplay.recording.models import RecordingMetrics, WorkerErrorCode
from quickreplay.replay.models import ReplayAsset


@dataclass(frozen=True, slots=True)
class ApplicationStateChanged:
    """The application changed its top-level state."""

    state: ApplicationState


@dataclass(frozen=True, slots=True)
class RecordingStarted:
    """Recording started and the input stream format is known."""

    stream_info: StreamInfo


@dataclass(frozen=True, slots=True)
class RecordingMetricsChanged:
    """Recording metrics were updated."""

    metrics: RecordingMetrics


@dataclass(frozen=True, slots=True)
class ReplayStarted:
    """A replay asset was opened for playback."""

    asset: ReplayAsset


@dataclass(frozen=True, slots=True)
class InputsChanged:
    """Input discovery completed."""

    request_id: UUID
    inputs: tuple[InputDescriptor, ...]


@dataclass(frozen=True, slots=True)
class ApplicationError:
    """A human-readable application error, with optional correlation data."""

    message: str
    source: str = "application"
    code: WorkerErrorCode | None = None
    request_id: UUID | None = None


type ApplicationEvent = (
    ApplicationStateChanged
    | RecordingStarted
    | RecordingMetricsChanged
    | ReplayStarted
    | InputsChanged
    | ApplicationError
)
