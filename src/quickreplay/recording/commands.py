"""Commands sent to the recorder worker process.

Every command is an immutable, picklable value object.  It must never contain a
multiprocessing object, native handle or open file.  Command handling is not
implemented in this phase.
"""

from dataclasses import dataclass
from uuid import UUID

from quickreplay.input.models import InputConfig


@dataclass(frozen=True, slots=True)
class StartRecording:
    """Start recording from the given input."""

    input_config: InputConfig


@dataclass(frozen=True, slots=True)
class PrepareReplay:
    """Freeze the current buffer and build a replay asset."""

    request_id: UUID


@dataclass(frozen=True, slots=True)
class ResumeRecording:
    """Resume recording after a replay has finished."""

    request_id: UUID


@dataclass(frozen=True, slots=True)
class ChangeInput:
    """Switch the active input."""

    request_id: UUID
    input_config: InputConfig


@dataclass(frozen=True, slots=True)
class DiscoverInputs:
    """Request the list of available inputs.

    ``camera_backend`` selects which OpenCV backend is probed for cameras;
    it defaults to ``"any"`` so existing callers keep their behaviour.
    """

    request_id: UUID
    camera_backend: str = "any"


@dataclass(frozen=True, slots=True)
class Shutdown:
    """Terminate the worker process."""


@dataclass(frozen=True, slots=True)
class StopSession:
    """Discard the active recording/replay session but keep the worker alive."""

    request_id: UUID


type WorkerCommand = (
    StartRecording
    | PrepareReplay
    | ResumeRecording
    | ChangeInput
    | DiscoverInputs
    | StopSession
    | Shutdown
)
