"""Application-level state machine.

The application has a single top-level state.  Transitions are described by a
small, explicit table; this is not a general state machine engine.
"""

from enum import StrEnum


class ApplicationState(StrEnum):
    """Top-level application state."""

    STARTING = "starting"
    IDLE = "idle"
    RECORDING = "recording"
    PREPARING_REPLAY = "preparing_replay"
    REPLAY = "replay"
    STOPPING = "stopping"
    RESUMING = "resuming"
    ERROR = "error"
    SHUTTING_DOWN = "shutting_down"


_ALLOWED_TRANSITIONS: dict[ApplicationState, frozenset[ApplicationState]] = {
    ApplicationState.STARTING: frozenset(
        {ApplicationState.IDLE, ApplicationState.ERROR, ApplicationState.SHUTTING_DOWN}
    ),
    ApplicationState.IDLE: frozenset(
        {
            ApplicationState.RECORDING,
            ApplicationState.ERROR,
            ApplicationState.SHUTTING_DOWN,
        }
    ),
    ApplicationState.RECORDING: frozenset(
        {
            ApplicationState.PREPARING_REPLAY,
            ApplicationState.STOPPING,
            ApplicationState.IDLE,
            ApplicationState.ERROR,
            ApplicationState.SHUTTING_DOWN,
        }
    ),
    ApplicationState.PREPARING_REPLAY: frozenset(
        {
            ApplicationState.REPLAY,
            ApplicationState.RECORDING,
            ApplicationState.ERROR,
            ApplicationState.SHUTTING_DOWN,
        }
    ),
    ApplicationState.REPLAY: frozenset(
        {
            ApplicationState.RESUMING,
            ApplicationState.STOPPING,
            ApplicationState.IDLE,
            ApplicationState.ERROR,
            ApplicationState.SHUTTING_DOWN,
        }
    ),
    ApplicationState.STOPPING: frozenset({ApplicationState.IDLE, ApplicationState.ERROR}),
    ApplicationState.RESUMING: frozenset(
        {
            ApplicationState.RECORDING,
            ApplicationState.ERROR,
            ApplicationState.SHUTTING_DOWN,
        }
    ),
    ApplicationState.ERROR: frozenset({ApplicationState.IDLE, ApplicationState.SHUTTING_DOWN}),
    ApplicationState.SHUTTING_DOWN: frozenset(),
}


def allowed_transitions(state: ApplicationState) -> frozenset[ApplicationState]:
    """States reachable from *state*."""
    return _ALLOWED_TRANSITIONS[state]


def can_transition(current: ApplicationState, target: ApplicationState) -> bool:
    """Return ``True`` if ``current -> target`` is an allowed transition."""
    return target in _ALLOWED_TRANSITIONS[current]
