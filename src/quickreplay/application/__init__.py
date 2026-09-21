"""Headless application layer.

The application controller coordinates the recorder worker process and the mpv
replay controller, and exposes a UI-independent state, snapshot and event API.
"""

from quickreplay.app.state import ApplicationState
from quickreplay.application.controller import (
    ApplicationController,
    ReplayControllerLike,
    WorkerHandle,
)
from quickreplay.application.errors import (
    ApplicationControllerError,
    ApplicationShutdownError,
    InvalidApplicationStateError,
    WorkerExitedError,
    WorkerStartupError,
)
from quickreplay.application.events import (
    ApplicationError,
    ApplicationEvent,
    ApplicationStateChanged,
    InputsChanged,
    RecordingMetricsChanged,
    RecordingStarted,
    ReplayStarted,
)
from quickreplay.application.models import (
    ApplicationControllerSettings,
    ApplicationSnapshot,
)

__all__ = [
    "ApplicationController",
    "ApplicationControllerError",
    "ApplicationControllerSettings",
    "ApplicationError",
    "ApplicationEvent",
    "ApplicationShutdownError",
    "ApplicationSnapshot",
    "ApplicationState",
    "ApplicationStateChanged",
    "InputsChanged",
    "InvalidApplicationStateError",
    "RecordingMetricsChanged",
    "RecordingStarted",
    "ReplayControllerLike",
    "ReplayStarted",
    "WorkerExitedError",
    "WorkerHandle",
    "WorkerStartupError",
]
