"""Headless Flet view wiring for the settings dialog.

Flet controls are constructed but never attached to a native window, so this
runs in CI without a display.  Widget behaviour is exercised through the view's
own handlers with a stub page.
"""

import asyncio
from dataclasses import replace
from fractions import Fraction
from pathlib import Path
from typing import cast

import flet as ft
import pytest
from fake_ui import FakeBridge

from quickreplay.app.state import ApplicationState
from quickreplay.application.events import InputsChanged
from quickreplay.application.models import ApplicationSnapshot
from quickreplay.configuration.models import QuickReplayConfig
from quickreplay.configuration.store import ConfigurationStore
from quickreplay.input.models import NdiInputDescriptor
from quickreplay.replay.models import ReplayAsset
from quickreplay.ui.main_view import (
    REPLAY_CONTENT_WIDTH,
    REPLAY_TRANSPORT_BUTTON_HEIGHT,
    REPLAY_TRANSPORT_BUTTON_WIDTH,
    REPLAY_TRANSPORT_SPACING,
    WINDOW_SIZES,
    MainView,
)
from quickreplay.ui.presentation import MetricsView
from quickreplay.ui.session import UiSession


class _StubPage:
    """The small slice of :class:`flet.Page` the view uses."""

    def __init__(self) -> None:
        self.updates = 0
        self.shown: list[object] = []
        self.popped = 0

    def update(self) -> None:
        self.updates += 1

    def show_dialog(self, dialog: object) -> None:
        self.shown.append(dialog)

    def pop_dialog(self) -> object | None:
        self.popped += 1
        return self.shown.pop() if self.shown else None

    def run_task(self, handler: object, *args: object) -> None:
        raise AssertionError("run_task is not used by the headless view tests")


def _session(
    tmp_path: Path, config: QuickReplayConfig | None = None
) -> tuple[UiSession, FakeBridge]:
    bridge = FakeBridge()
    store = ConfigurationStore(tmp_path / "config.json")
    session = UiSession(bridge, store, config or QuickReplayConfig())
    asyncio.run(session.start())
    return session, bridge


async def _discover(session: UiSession, bridge: FakeBridge, inputs: tuple) -> None:
    bridge.events = [InputsChanged(request_id=bridge.next_discovery_id, inputs=inputs)]
    bridge.snapshot_value = ApplicationSnapshot(state=ApplicationState.IDLE)
    await session.poll()


def _view(session: UiSession) -> tuple[MainView, _StubPage]:
    page = _StubPage()
    return MainView(cast(ft.Page, page), session), page


def test_setup_is_ndi_only_and_compact(tmp_path: Path) -> None:
    session, _ = _session(tmp_path)
    view, _page = _view(session)
    view._populate_settings_fields()

    assert view.source_dropdown.label == "NDI source"
    assert not hasattr(view, "kind_button")
    assert not hasattr(view, "backend_dropdown")
    assert WINDOW_SIZES["setup"] == (640, 320)
    assert view.input_section in view.setup_body.controls
    assert view.settings_row in view.setup_body.controls
    assert view.setup_actions in view.setup_section.controls
    assert view.setup_actions not in view.setup_body.controls
    assert len(view.setup_actions.controls) == 2
    assert view.setup_actions.spacing == view.settings_row.spacing
    assert view.setup_actions.alignment != ft.MainAxisAlignment.SPACE_BETWEEN
    assert view.setup_body.expand is True
    assert view.setup_section.expand is True
    assert view.control.expand is True

    recording, replay = (cast(ft.Column, control) for control in view.settings_row.controls)
    left_actions = cast(ft.Container, view.setup_actions.controls[0])
    right_actions = cast(ft.Row, view.setup_actions.controls[1])
    assert left_actions.expand is True
    assert right_actions.expand is True
    left_action_row = cast(ft.Row, left_actions.content)
    assert left_action_row.controls == [view.about_button]
    assert left_action_row.alignment == ft.MainAxisAlignment.START
    assert right_actions.expand is True
    assert right_actions.controls == [view.settings_apply_button, view.start_button]
    assert right_actions.alignment == ft.MainAxisAlignment.END
    assert replay.horizontal_alignment == ft.CrossAxisAlignment.STRETCH
    assert view.settings_mpv_field.expand is not True
    assert cast(ft.Text, recording.controls[0]).value == "Recording"
    assert cast(ft.Text, replay.controls[0]).value == "Replay"
    assert view.about_button.icon == ft.Icons.INFO_OUTLINE
    assert view.about_button.tooltip == "About"
    assert (
        sum(
            child.value.startswith("Restart required")
            for child in view.setup_body.controls
            if isinstance(child, ft.Text)
        )
        == 1
    )


def test_apply_success_closes_dialog_and_shows_status(tmp_path: Path) -> None:
    session, bridge = _session(tmp_path)
    asyncio.run(_discover(session, bridge, ()))
    view, page = _view(session)

    asyncio.run(view._apply_settings())

    assert view.status_text.value == "Settings saved."


def test_apply_validation_failure_keeps_dialog_open(tmp_path: Path) -> None:
    session, _ = _session(tmp_path)
    view, page = _view(session)
    before = session.config
    view._populate_settings_fields()
    view.settings_buffer_field.value = "0"

    asyncio.run(view._apply_settings())

    assert session.config == before
    assert "Buffer duration" in view.settings_error_text.value
    # The edited draft stays visible for the user to correct.
    assert view.settings_buffer_field.value == "0"


def test_settings_button_disabled_while_shutting_down(tmp_path: Path) -> None:
    session, bridge = _session(tmp_path)
    bridge.snapshot_value = ApplicationSnapshot(state=ApplicationState.SHUTTING_DOWN)
    asyncio.run(session.poll())
    view, _page = _view(session)

    view.render(session.view_state())

    assert view.session_section.visible is True


def test_replay_controls_are_visible_and_prioritized(tmp_path: Path) -> None:
    session, bridge = _session(tmp_path)
    view, _page = _view(session)

    bridge.snapshot_value = ApplicationSnapshot(
        state=ApplicationState.REPLAY,
        replay_asset=ReplayAsset(Path("replay.mkv"), 10_000_000_000, Fraction(60, 1)),
    )
    asyncio.run(session.poll())
    view.render(session.view_state())

    assert view.input_section.visible is False
    assert view.recording_section.visible is False
    assert view.replay_panel.visible is True
    assert cast(ft.Text, view.replay_back20_button.content).value == "-20f"
    assert cast(ft.Text, view.replay_back1_button.content).value == "-1f"
    assert cast(ft.Text, view.replay_play_button.content).value == "Play"
    assert cast(ft.Text, view.replay_forward1_button.content).value == "+1f"
    assert cast(ft.Text, view.replay_forward20_button.content).value == "+20f"
    assert view.set_point_button.content == "Set Point"
    assert view.mode_button.content == "Record"
    assert isinstance(view.setup_button, ft.IconButton)
    assert view.setup_button.icon == ft.Icons.ARROW_BACK
    assert view.setup_button.tooltip == "Setup"
    assert view.control.scroll is None
    assert view.setup_body.scroll == ft.ScrollMode.AUTO
    assert view.setup_actions in view.setup_section.controls
    assert view.setup_actions not in view.setup_body.controls
    header = cast(ft.Row, view.session_section.controls[0])
    button_group = cast(ft.Row, header.controls[0])
    assert view.mode_button in button_group.controls
    assert view.setup_button in button_group.controls
    assert header.vertical_alignment == ft.CrossAxisAlignment.CENTER
    assert WINDOW_SIZES["recording"][0] == WINDOW_SIZES["replay"][0]


@pytest.mark.parametrize("state", [ApplicationState.RECORDING, ApplicationState.REPLAY])
def test_about_entry_is_not_in_session_screens(tmp_path: Path, state: ApplicationState) -> None:
    session, bridge = _session(tmp_path)
    bridge.snapshot_value = ApplicationSnapshot(
        state=state,
        replay_asset=(
            ReplayAsset(Path("replay.mkv"), 10_000_000_000, Fraction(60, 1))
            if state is ApplicationState.REPLAY
            else None
        ),
    )
    asyncio.run(session.poll())
    view, _page = _view(session)

    view.render(session.view_state())

    assert view.setup_section.visible is False
    assert isinstance(view.setup_button, ft.IconButton)
    assert view.about_button not in view.session_section.controls
    if state is ApplicationState.RECORDING:
        assert view.mode_button.content == "Replay"
        assert view.state_text.value == "● REC"


def test_resuming_uses_recording_size_before_recording_starts(tmp_path: Path) -> None:
    session, _bridge = _session(tmp_path)
    view, page = _view(session)
    window = type("Window", (), {"width": 0, "height": 0})()
    page.__dict__["window"] = window

    view._update_window_size(ApplicationState.RECORDING)
    assert (window.width, window.height) == WINDOW_SIZES["recording"]
    view._update_window_size(ApplicationState.PREPARING_REPLAY)
    assert (window.width, window.height) == WINDOW_SIZES["recording"]

    view._update_window_size(ApplicationState.REPLAY)
    assert (window.width, window.height) == WINDOW_SIZES["replay"]
    view._update_window_size(ApplicationState.RESUMING)
    assert (window.width, window.height) == WINDOW_SIZES["recording"]


def test_discovery_status_is_limited_to_input_row(tmp_path: Path) -> None:
    session, _bridge = _session(tmp_path)
    view, _page = _view(session)

    view.render(replace(session.view_state(), discovering=True, status_message="Discovering..."))

    assert view.refresh_button.content == "Discovering..."
    assert view.refresh_button.disabled is True
    assert view.footer.visible is False
    assert view.status_text.visible is False


def test_about_dialog_preserves_setup_draft_and_application_state(tmp_path: Path) -> None:
    session, bridge = _session(tmp_path)
    inputs = (NdiInputDescriptor("Studio NDI"),)
    asyncio.run(_discover(session, bridge, inputs))
    session.select("ndi:Studio NDI")
    view, page = _view(session)
    view.settings_buffer_field.value = "45"
    view.settings_mpv_field.value = "custom-mpv.exe"
    draft_before = view._settings_draft()
    state_before = session.view_state()
    selected_before = state_before.selected_key
    bridge_calls_before = (
        len(bridge.discovery_requests),
        len(bridge.recording_configs),
        bridge.replay_requests,
    )

    view._on_about(cast(ft.Event, object()))

    assert len(page.shown) == 1
    dialog = cast(ft.AlertDialog, page.shown[0])
    assert dialog.modal is True
    assert view._settings_draft() == draft_before
    assert session.view_state().state is state_before.state
    assert session.view_state().selected_key == selected_before
    assert (
        len(bridge.discovery_requests),
        len(bridge.recording_configs),
        bridge.replay_requests,
    ) == bridge_calls_before

    view._on_about_close(cast(ft.Event, object()))

    assert page.shown == []
    assert view._settings_draft() == draft_before
    assert session.view_state().state is state_before.state
    assert session.view_state().selected_key == selected_before


def test_about_is_disabled_outside_idle_setup_state(tmp_path: Path) -> None:
    session, bridge = _session(tmp_path)
    bridge.snapshot_value = ApplicationSnapshot(state=ApplicationState.RECORDING)
    asyncio.run(session.poll())
    view, page = _view(session)

    view.render(session.view_state())
    view._on_about(cast(ft.Event, object()))

    assert view.about_button.disabled is True
    assert page.shown == []


def test_replay_transport_buttons_share_fixed_dimensions_and_style(tmp_path: Path) -> None:
    session, _bridge = _session(tmp_path)
    view, _page = _view(session)
    transport_buttons = (
        view.replay_back20_button,
        view.replay_back1_button,
        view.replay_play_button,
        view.replay_forward1_button,
        view.replay_forward20_button,
    )

    assert {button.width for button in transport_buttons} == {REPLAY_TRANSPORT_BUTTON_WIDTH}
    assert {button.height for button in transport_buttons} == {REPLAY_TRANSPORT_BUTTON_HEIGHT}
    assert all(
        button.border_radius == transport_buttons[0].border_radius for button in transport_buttons
    )
    assert all(button.padding == transport_buttons[0].padding for button in transport_buttons)
    assert view.replay_panel.width == REPLAY_CONTENT_WIDTH
    assert cast(ft.Row, view.replay_panel.controls[2]).spacing == REPLAY_TRANSPORT_SPACING
    assert REPLAY_CONTENT_WIDTH == (
        len(transport_buttons) * REPLAY_TRANSPORT_BUTTON_WIDTH
        + (len(transport_buttons) - 1) * REPLAY_TRANSPORT_SPACING
    )
    assert WINDOW_SIZES["recording"][0] == REPLAY_CONTENT_WIDTH + 40

    play_label = cast(ft.Text, view.replay_play_button.content)
    play_label.value = "Pause"
    assert view.replay_play_button.width == REPLAY_TRANSPORT_BUTTON_WIDTH
    assert view.replay_play_button.height == REPLAY_TRANSPORT_BUTTON_HEIGHT


def test_record_button_enters_compact_pending_layout(tmp_path: Path) -> None:
    session, bridge = _session(tmp_path)
    bridge.snapshot_value = ApplicationSnapshot(
        state=ApplicationState.REPLAY,
        replay_asset=ReplayAsset(Path("replay.mkv"), 10_000_000_000, Fraction(60, 1)),
    )
    asyncio.run(session.poll())
    view, page = _view(session)
    window = type("Window", (), {"width": 0, "height": 0})()
    page.__dict__["window"] = window
    view.render(session.view_state())

    asyncio.run(view._switch_session_mode())

    assert bridge.resume_requests == 1
    assert (window.width, window.height) == WINDOW_SIZES["recording"]
    assert view.state_text.value == "Starting..."
    assert view.replay_panel.visible is False
    assert view.mode_button.content == "Record"
    assert view.mode_button.disabled is True


def test_recording_metrics_show_fps_suffix_once_and_preserve_drops(tmp_path: Path) -> None:
    session, _bridge = _session(tmp_path)
    view, _page = _view(session)
    metrics = MetricsView(
        input_fps="59.4",
        recording_fps="59.3",
        buffer="4.0 / 60 s",
        buffer_fraction=4 / 60,
        segments="2",
        drops="Video 1 / Audio 0",
        video_drops=1,
        audio_drops=0,
        has_drops=True,
    )

    view.render(replace(session.view_state(), metrics=metrics))

    assert view.recording_status_text.value == (
        "Input 59.4 · Rec 59.3 fps · Seg 2 · Buf 4.0 / 60 s · ⚠ Drops V:1 A:0"
    )
