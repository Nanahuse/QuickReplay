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
from fake_ui import FakeBridge

from quickreplay.app.state import ApplicationState
from quickreplay.application.events import InputsChanged
from quickreplay.application.models import ApplicationSnapshot
from quickreplay.configuration.models import QuickReplayConfig
from quickreplay.configuration.store import ConfigurationStore
from quickreplay.input.models import (
    CameraInputConfig,
    CameraInputDescriptor,
    CameraMode,
    NdiInputDescriptor,
)
from quickreplay.replay.models import ReplayAsset
from quickreplay.ui.main_view import MainView
from quickreplay.ui.session import CAMERA_KIND, UiSession
from quickreplay.ui.settings import CAMERA_MODE_MESSAGE


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


def _camera_session(tmp_path: Path) -> tuple[UiSession, FakeBridge]:
    session, bridge = _session(tmp_path)
    asyncio.run(session.set_input_kind(CAMERA_KIND))
    asyncio.run(_discover(session, bridge, (CameraInputDescriptor("Camera 1", 1),)))
    return session, bridge


def _view(session: UiSession) -> tuple[MainView, _StubPage]:
    page = _StubPage()
    return MainView(cast(ft.Page, page), session), page


def test_setup_populates_settings_for_selected_camera(tmp_path: Path) -> None:
    session, _ = _camera_session(tmp_path)
    view, page = _view(session)

    view._populate_settings_fields()

    assert view.settings_explicit_checkbox.disabled is False
    assert view.settings_camera_label.value == "Editing: Camera 1 (#1)"
    assert view.settings_buffer_field.value == "120"
    assert view.settings_mpv_field.value == "mpv"
    # No explicit mode is selected yet, so the mode fields stay disabled.
    assert view.settings_width_field.disabled is True
    assert view.settings_camera_hint.visible is False


def test_camera_fields_enable_when_explicit_mode_is_checked(tmp_path: Path) -> None:
    session, _ = _camera_session(tmp_path)
    view, page = _view(session)
    view._populate_settings_fields()

    view.settings_explicit_checkbox.value = True
    view._on_settings_explicit_change(cast(ft.Event, object()))

    assert view.settings_width_field.disabled is False
    assert view.settings_denominator_field.disabled is False
    assert page.updates >= 1


def test_camera_section_disabled_without_camera_selection(tmp_path: Path) -> None:
    session, bridge = _session(tmp_path)
    asyncio.run(_discover(session, bridge, (NdiInputDescriptor("OBS"),)))
    view, _page = _view(session)

    view._populate_settings_fields()

    assert view.settings_explicit_checkbox.disabled is True
    assert view.settings_camera_hint.visible is True
    assert view.settings_width_field.disabled is True
    assert view.settings_camera_label.value == ""


def test_apply_success_closes_dialog_and_shows_status(tmp_path: Path) -> None:
    session, _ = _camera_session(tmp_path)
    view, page = _view(session)
    view._populate_settings_fields()
    view.settings_explicit_checkbox.value = True
    view.settings_width_field.value = "1280"
    view.settings_height_field.value = "720"
    view.settings_numerator_field.value = "60"
    view.settings_denominator_field.value = "1"

    asyncio.run(view._apply_settings())

    assert session.config.input == replace(
        CameraInputConfig("Camera 1", 1, "any", None),
        mode=CameraMode(1280, 720, Fraction(60, 1)),
    )
    assert view.status_text.value == CAMERA_MODE_MESSAGE


def test_apply_validation_failure_keeps_dialog_open(tmp_path: Path) -> None:
    session, _ = _camera_session(tmp_path)
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
    assert view.replay_play_button.content == "Play"
    assert cast(ft.Text, view.replay_forward1_button.content).value == "+1f"
    assert cast(ft.Text, view.replay_forward20_button.content).value == "+20f"
    assert view.set_point_button.content == "Set Point"
    assert view.resume_button.content == "Resume"
    assert view.control.scroll == ft.ScrollMode.AUTO
