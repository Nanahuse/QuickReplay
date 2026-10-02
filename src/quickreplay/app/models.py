"""Read-only application view models.

A future UI layer renders these instead of holding references to runtime
workers or native objects.
"""

from dataclasses import dataclass

from quickreplay.app.state import ApplicationState
from quickreplay.input.models import StreamInfo
from quickreplay.replay.models import SetPoint


@dataclass(frozen=True, slots=True)
class ApplicationViewState:
    """Snapshot of everything a UI needs to render the current state."""

    state: ApplicationState

    input_name: str | None = None
    stream_info: StreamInfo | None = None

    buffer_duration_ns: int = 0

    replay_position_ns: int | None = None
    set_point: SetPoint | None = None

    error_message: str | None = None
