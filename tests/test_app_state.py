"""Tests for the application state machine."""

from quickreplay.app.state import ApplicationState, allowed_transitions, can_transition


def test_all_states_exist() -> None:
    assert {state.name for state in ApplicationState} == {
        "STARTING",
        "IDLE",
        "RECORDING",
        "PREPARING_REPLAY",
        "REPLAY",
        "RESUMING",
        "ERROR",
        "SHUTTING_DOWN",
    }


def test_replay_cycle_transitions_are_allowed() -> None:
    assert can_transition(ApplicationState.RECORDING, ApplicationState.PREPARING_REPLAY)
    assert can_transition(ApplicationState.PREPARING_REPLAY, ApplicationState.REPLAY)
    assert can_transition(ApplicationState.REPLAY, ApplicationState.RESUMING)
    assert can_transition(ApplicationState.RESUMING, ApplicationState.RECORDING)


def test_invalid_transition_is_rejected() -> None:
    assert not can_transition(ApplicationState.IDLE, ApplicationState.REPLAY)
    assert not can_transition(ApplicationState.RECORDING, ApplicationState.REPLAY)
    assert not can_transition(ApplicationState.SHUTTING_DOWN, ApplicationState.IDLE)


def test_allowed_transitions_matches_can_transition() -> None:
    for state in ApplicationState:
        for target in ApplicationState:
            assert can_transition(state, target) == (target in allowed_transitions(state))
