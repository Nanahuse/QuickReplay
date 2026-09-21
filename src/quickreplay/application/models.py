"""Application-level settings and read-only snapshots."""

from dataclasses import dataclass, field

from quickreplay.app.state import ApplicationState
from quickreplay.input.models import StreamInfo
from quickreplay.recording.models import RecordingMetrics
from quickreplay.replay.controller import ReplayControllerSettings
from quickreplay.replay.models import ReplayAsset
from quickreplay.worker.settings import RecorderWorkerSettings


@dataclass(frozen=True, slots=True)
class ApplicationControllerSettings:
    """Runtime settings for the application controller.

    The recorder/replay component settings are embedded, not duplicated.  They
    are only needed when the controller builds the components itself; tests
    inject ready-made fakes instead.
    """

    worker: RecorderWorkerSettings | None = None
    replay: ReplayControllerSettings = field(default_factory=ReplayControllerSettings)
    worker_start_timeout_seconds: float = 5.0
    worker_shutdown_timeout_seconds: float = 5.0


@dataclass(frozen=True, slots=True)
class ApplicationSnapshot:
    """A read-only view of the current application state for a UI."""

    state: ApplicationState
    stream_info: StreamInfo | None = None
    metrics: RecordingMetrics | None = None
    replay_asset: ReplayAsset | None = None
    error_message: str | None = None
