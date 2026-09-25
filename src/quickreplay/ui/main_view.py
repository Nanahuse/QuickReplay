"""Flet 1.0 controls for the QuickReplay main window.

The view is intentionally thin: it renders a
:class:`~quickreplay.ui.session.UiViewState` and forwards user actions to
:class:`~quickreplay.ui.session.UiSession`.  All application state lives in the
session; the view holds only transient widget state.
"""

import asyncio
import subprocess
import sys
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum, auto
from pathlib import Path
from typing import Any, cast

import flet as ft

from quickreplay.app.state import ApplicationState
from quickreplay.ui.presentation import format_duration_ns
from quickreplay.ui.replay_repeat import ReplayActionRepeater
from quickreplay.ui.session import (
    ReplayView,
    UiSession,
    UiViewState,
)
from quickreplay.ui.settings import SettingsDraft

POLL_INTERVAL_SECONDS = 0.1
POLL_INTERVAL_REPLAY_SECONDS = 0.05
_EMPTY = "—"
_NANOSECONDS_PER_SECOND = 1_000_000_000
_DESTROYED_SESSION_MARKER = "destroyed session"
REPLAY_REPEAT_FRAME_INTERVAL_SECONDS = 0.085
REPLAY_REPEAT_FAST_INTERVAL_SECONDS = 0.050
REPLAY_FAST_MOVE_FRAMES = 20
SESSION_WINDOW_WIDTH = 420
SETUP_WINDOW_SIZE = (640, 320)
RECORDING_WINDOW_HEIGHT = 120
REPLAY_WINDOW_HEIGHT = 300
REPLAY_CONTENT_WIDTH = 380
REPLAY_TRANSPORT_BUTTON_WIDTH = 68
REPLAY_TRANSPORT_BUTTON_HEIGHT = 40
REPLAY_TRANSPORT_SPACING = 10
WINDOW_SIZES = {
    "setup": SETUP_WINDOW_SIZE,
    "recording": (SESSION_WINDOW_WIDTH, RECORDING_WINDOW_HEIGHT),
    "replay": (SESSION_WINDOW_WIDTH, REPLAY_WINDOW_HEIGHT),
}


class ViewLifecycle(Enum):
    """MainView lifecycle state.

    Only :attr:`RUNNING` accepts new UI work and page updates; :attr:`CLOSING`
    rejects them while core cleanup runs, and :attr:`CLOSED` is terminal.
    """

    RUNNING = auto()
    CLOSING = auto()
    CLOSED = auto()


def is_destroyed_session_error(exc: RuntimeError) -> bool:
    """Whether *exc* is Flet's known "session destroyed" teardown error.

    Flet raises this when the page's session has been torn down (window
    destroyed or client disconnected).  Only this specific error is treated as
    a lifecycle event; every other :class:`RuntimeError` is a real bug and is
    left to propagate.  The string check is deliberately confined here.
    """
    return _DESTROYED_SESSION_MARKER in str(exc)


def slider_seconds_to_ns(value: float) -> int:
    """Convert a Slider value (seconds) to integer nanoseconds at the UI boundary."""
    return int(Decimal(str(value)) * _NANOSECONDS_PER_SECOND)


@dataclass(slots=True)
class SeekDrag:
    """Pure seek-bar drag state (no Flet types), so it can be tested headlessly.

    While ``active`` the view must not overwrite the slider thumb with the
    polled position, and no seek command is sent until :meth:`end`.
    """

    active: bool = False
    preview_ns: int | None = None

    def start(self, value: float) -> None:
        self.active = True
        self.preview_ns = slider_seconds_to_ns(value)

    def update_preview(self, value: float) -> None:
        self.preview_ns = slider_seconds_to_ns(value)

    def end(self, value: float) -> int:
        target_ns = slider_seconds_to_ns(value)
        self.preview_ns = target_ns
        self.active = False
        return target_ns


class MainView:
    """The single main screen of the QuickReplay desktop UI."""

    def __init__(self, page: ft.Page, session: UiSession) -> None:
        self.page = page
        self.session = session
        self._lifecycle = ViewLifecycle.RUNNING
        self._session_lost = False
        self._close_started = False
        self._poll_task: asyncio.Task[None] | None = None
        self._about_process: Any | None = None
        self._starting = False
        self._start_done = asyncio.Event()
        self._replay_repeater = ReplayActionRepeater()
        self._replay_repeat_active = False
        self._window_mode: str | None = None
        self._stable_session_mode: str | None = None
        self._resume_in_progress = False

        self.state_text = ft.Text("", weight=ft.FontWeight.BOLD)
        self.source_dropdown = ft.Dropdown(
            label="NDI source", options=[], width=440, on_select=self._on_source_select
        )
        self.refresh_button = ft.FilledButton(content="Refresh", on_click=self._on_refresh)
        self.start_button = ft.FilledButton(content="Start Recording", on_click=self._on_start)
        self.mode_button = ft.FilledButton(content="Replay", on_click=self._on_mode_button)

        self.replay_fps_text = ft.Text(_EMPTY)

        # Replay panel (only visible while replaying).
        self._seek_drag = SeekDrag()
        self.replay_position_text = ft.Text(_EMPTY)
        self.replay_slider = ft.Slider(
            min=0,
            max=1,
            value=0,
            on_change_start=self._on_seek_start,
            on_change=self._on_seek_change,
            on_change_end=self._on_seek_end,
        )
        self.replay_play_button = self._transport_button("Play", self._on_play_pause)
        self.replay_back20_button, self.replay_back20_gesture = self._repeat_button(
            "-20f",
            lambda: self.session.seek_frames(-REPLAY_FAST_MOVE_FRAMES),
            REPLAY_REPEAT_FAST_INTERVAL_SECONDS,
        )
        self.replay_back1_button, self.replay_back1_gesture = self._repeat_button(
            "-1f", self.session.step_backward, REPLAY_REPEAT_FRAME_INTERVAL_SECONDS
        )
        self.replay_forward1_button, self.replay_forward1_gesture = self._repeat_button(
            "+1f", self.session.step_forward, REPLAY_REPEAT_FRAME_INTERVAL_SECONDS
        )
        self.replay_forward20_button, self.replay_forward20_gesture = self._repeat_button(
            "+20f",
            lambda: self.session.seek_frames(REPLAY_FAST_MOVE_FRAMES),
            REPLAY_REPEAT_FAST_INTERVAL_SECONDS,
        )
        self.set_point_text = ft.Text(_EMPTY)
        self.time_difference_text = ft.Text(_EMPTY)
        self.frame_difference_text = ft.Text(_EMPTY)
        self.set_point_button = ft.FilledButton(content="Set Point", on_click=self._on_set_point)
        self.replay_panel = ft.Column(
            controls=[
                ft.Row(controls=[self.replay_position_text, ft.Text("·"), self.replay_fps_text]),
                self.replay_slider,
                ft.Row(
                    controls=[
                        self.replay_back20_gesture,
                        self.replay_back1_gesture,
                        self.replay_play_button,
                        self.replay_forward1_gesture,
                        self.replay_forward20_gesture,
                    ],
                    spacing=REPLAY_TRANSPORT_SPACING,
                ),
                ft.Row(
                    controls=[self.time_difference_text, ft.Text("·"), self.frame_difference_text]
                ),
                self.set_point_button,
            ],
            spacing=10,
            width=REPLAY_CONTENT_WIDTH,
            visible=False,
        )

        self.input_section = ft.Column(
            controls=[
                ft.Text("Input", weight=ft.FontWeight.BOLD),
                ft.Row(controls=[self.source_dropdown, self.refresh_button]),
            ],
            spacing=10,
        )
        self.recording_status_text = ft.Text("", color=ft.Colors.BLUE_GREY)
        self.recording_section = ft.Column(
            controls=[self.recording_status_text], spacing=4, tight=True
        )

        # Setup settings fields (validation and persistence remain in UiSession).
        self.settings_buffer_field = ft.TextField(label="Buffer duration", width=180)
        self.settings_mpv_field = ft.TextField(label="mpv executable")
        self.settings_error_text = ft.Text("", color=ft.Colors.RED, visible=False)
        self.setup_status_text = ft.Text("", color=ft.Colors.BLUE_GREY, visible=False)
        self.setup_error_text = ft.Text("", color=ft.Colors.RED, visible=False)
        self.settings_apply_button = ft.FilledButton(
            content="Apply", on_click=self._on_settings_apply
        )
        self.about_button = ft.IconButton(
            icon=ft.Icons.INFO_OUTLINE,
            tooltip="About",
            on_click=self._on_about,
        )

        self.setup_button = ft.IconButton(
            icon=ft.Icons.ARROW_BACK,
            tooltip="Setup",
            on_click=self._on_setup,
        )
        recording_settings = ft.Column(
            controls=[
                ft.Text("Recording", weight=ft.FontWeight.BOLD),
                ft.Row(controls=[self.settings_buffer_field, ft.Text("seconds")]),
            ],
            spacing=6,
            tight=True,
            expand=True,
        )
        replay_settings = ft.Column(
            controls=[
                ft.Text("Replay", weight=ft.FontWeight.BOLD),
                self.settings_mpv_field,
            ],
            spacing=6,
            tight=True,
            expand=True,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
        )
        self.settings_row = ft.Row(
            controls=[recording_settings, replay_settings],
            spacing=24,
            vertical_alignment=ft.CrossAxisAlignment.START,
        )
        self.settings_restart_note = ft.Text(
            "Restart required after changing these settings", italic=True
        )
        self.setup_body = ft.Column(
            controls=[
                self.input_section,
                ft.Divider(),
                self.settings_row,
                self.settings_restart_note,
                self.settings_error_text,
                self.setup_status_text,
                self.setup_error_text,
            ],
            spacing=6,
            expand=True,
            scroll=ft.ScrollMode.AUTO,
        )
        left_actions = ft.Container(
            expand=True,
            content=ft.Row(
                controls=[self.about_button],
                alignment=ft.MainAxisAlignment.START,
            ),
        )
        right_actions = ft.Row(
            controls=[self.settings_apply_button, self.start_button],
            alignment=ft.MainAxisAlignment.END,
            spacing=8,
            expand=True,
        )
        self.setup_actions = ft.Row(
            controls=[left_actions, right_actions],
            spacing=self.settings_row.spacing,
            height=52,
        )
        self.setup_section = ft.Column(
            controls=[self.setup_body, self.setup_actions], spacing=4, expand=True
        )
        self.session_section = ft.Column(
            controls=[
                ft.Row(
                    controls=[
                        ft.Row(controls=[self.setup_button, self.mode_button]),
                        self.state_text,
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                self.recording_section,
                self.replay_panel,
            ],
            spacing=4,
            tight=True,
        )

        self.status_text = ft.Text("", color=ft.Colors.BLUE_GREY)
        self.error_text = ft.Text("", color=ft.Colors.RED)

        self.footer = ft.Column(controls=[self.status_text, self.error_text], spacing=4, tight=True)
        self.control = ft.Column(
            controls=[self.setup_section, self.session_section, self.footer],
            spacing=4,
            expand=True,
        )
        self._populate_settings_fields()

    # -- lifecycle ---------------------------------------------------------
    @property
    def lifecycle(self) -> ViewLifecycle:
        """The current view lifecycle state."""
        return self._lifecycle

    @property
    def is_active(self) -> bool:
        """Whether the view still accepts UI work and page updates."""
        return self._lifecycle is ViewLifecycle.RUNNING and not self._session_lost

    async def start(self) -> None:
        """Start the application and render the first frame.

        If starting fails, the partially created core resources are shut down
        before the error propagates, so no worker or executor is leaked.  A
        close requested while starting waits for this to finish.
        """
        if not self.is_active:
            return
        self._starting = True
        try:
            await self.session.start()
        except Exception:
            self._starting = False
            self._start_done.set()
            await self.close(destroy_window=False)
            raise
        else:
            self._starting = False
            self._start_done.set()
        self._populate_settings_fields()
        await self._render_and_update()

    def start_polling(self) -> None:
        """Start the background poll task (idempotent, RUNNING only)."""
        if not self.is_active or self._poll_task is not None:
            return
        self.page.run_task(self._poll_entry)

    async def _poll_entry(self) -> None:
        self._poll_task = asyncio.current_task()
        try:
            await self.poll_loop()
        finally:
            self._poll_task = None

    async def poll_loop(self) -> None:
        try:
            while self.is_active:
                try:
                    await self.session.poll()
                except Exception as exc:  # noqa: BLE001 - surface poll failures in the UI
                    if not self.is_active:
                        break
                    self.session.note_error(f"UI poll failed: {exc}")
                if not self.is_active:
                    break
                state = self.session.view_state()
                self.render(state)
                if not self._update_page():
                    break
                interval = (
                    POLL_INTERVAL_REPLAY_SECONDS
                    if state.state is ApplicationState.REPLAY
                    else POLL_INTERVAL_SECONDS
                )
                await asyncio.sleep(interval)
        except asyncio.CancelledError:
            # Explicit cancellation is the normal way to stop polling; it is
            # not a UI error.
            pass
        finally:
            if self._session_lost:
                await self.close(destroy_window=False)

    def on_window_event(self, event: ft.WindowEvent) -> None:
        if getattr(event, "type", None) == ft.WindowEventType.CLOSE:
            self._launch_close(destroy_window=True)

    def on_page_disconnect(self, *_args: object) -> None:
        """Supplementary cleanup trigger for Flet session disconnects.

        The primary desktop path is :meth:`on_window_event`; this only exists
        because Flet may report a client disconnect first.
        """
        self._session_lost = True
        self._launch_close(destroy_window=False)

    async def close(self, *, destroy_window: bool = True) -> None:
        """Shut the application down once, then optionally destroy the window.

        Core cleanup (session/bridge/controller/worker/mpv) and the Flet window
        destruction are separate phases: a lost session skips the window step.
        Repeated or concurrent calls are no-ops after the first one starts.
        """
        if self._lifecycle is not ViewLifecycle.RUNNING:
            return
        self._lifecycle = ViewLifecycle.CLOSING
        errors: list[Exception] = []
        try:
            await self._replay_repeater.stop()
            if self._starting and not self._start_done.is_set():
                # Never tear the core down in the middle of a start.
                await self._start_done.wait()
            try:
                await self._stop_polling()
            except Exception as exc:  # noqa: BLE001 - keep cleaning up
                errors.append(exc)
            try:
                await self.session.shutdown()
            except Exception as exc:  # noqa: BLE001 - keep cleaning up
                errors.append(exc)
            try:
                await self._stop_about_process()
            except Exception as exc:  # noqa: BLE001 - continue window teardown
                errors.append(exc)
        finally:
            self._lifecycle = ViewLifecycle.CLOSED
        if destroy_window:
            try:
                await self._destroy_window()
            except Exception as exc:  # noqa: BLE001 - core cleanup already done
                errors.append(exc)
        if errors:
            raise errors[0]

    async def _stop_polling(self) -> None:
        task = self._poll_task
        if task is None or task.done():
            return
        if task is asyncio.current_task():
            # The poll loop itself initiated the close; it finishes on return.
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def _stop_about_process(self) -> None:
        process = self._about_process
        self._about_process = None
        if process is None:
            return
        if process.poll() is not None:
            return
        try:
            await asyncio.to_thread(process.wait, timeout=2.0)
            return
        except subprocess.TimeoutExpired:
            pass
        process.terminate()
        try:
            await asyncio.to_thread(process.wait, timeout=1.0)
            return
        except subprocess.TimeoutExpired:
            process.kill()
            await asyncio.to_thread(process.wait, timeout=1.0)
        if process.poll() is None:
            raise RuntimeError("About process did not exit during application shutdown")

    async def _destroy_window(self) -> None:
        if self._session_lost:
            return
        try:
            await self.page.window.destroy()
        except RuntimeError as exc:
            if not is_destroyed_session_error(exc):
                raise
            self._session_lost = True

    def _launch_close(self, *, destroy_window: bool) -> None:
        if self._lifecycle is not ViewLifecycle.RUNNING or self._close_started:
            return
        self._close_started = True
        try:
            self.page.run_task(self.close, destroy_window=destroy_window)
        except RuntimeError as exc:
            if not is_destroyed_session_error(exc):
                raise
            self._session_lost = True
            asyncio.ensure_future(self.close(destroy_window=False))

    # -- page access -------------------------------------------------------
    def _update_page(self) -> bool:
        """Update the page unless closing/closed.

        A destroyed Flet session is treated as a lifecycle event: the view
        stops accepting work and the caller (poll loop / action helper) runs
        the core shutdown.  Any other ``RuntimeError`` propagates.
        """
        if not self.is_active:
            return False
        try:
            self.page.update()
        except RuntimeError as exc:
            if not is_destroyed_session_error(exc):
                raise
            self._session_lost = True
            self._launch_close(destroy_window=False)
            return False
        return True

    def _refresh_view(self) -> None:
        """Render and update from a synchronous handler."""
        if not self.is_active:
            return
        self.render(self.session.view_state())
        if not self._update_page() and self._session_lost:
            self._launch_close(destroy_window=False)

    def _run_task(self, handler: Callable[..., Awaitable[None]], *args: object) -> None:
        """Launch an async UI action unless the view is closing/closed."""
        if not self.is_active:
            return
        try:
            self.page.run_task(handler, *args)
        except RuntimeError as exc:
            if not is_destroyed_session_error(exc):
                raise
            self._session_lost = True
            self._launch_close(destroy_window=False)

    async def _render_and_update(self) -> None:
        """Render after an action, or run core cleanup if the session was lost."""
        if not self.is_active:
            if self._session_lost:
                await self.close(destroy_window=False)
            return
        self.render(self.session.view_state())
        if not self._update_page() and self._session_lost:
            await self.close(destroy_window=False)

    async def _run_action(self, operation: Callable[[], Awaitable[None]]) -> None:
        """Run an async UI action and refresh the view only while running."""
        if not self.is_active:
            return
        await operation()
        await self._render_and_update()

    # -- rendering ---------------------------------------------------------
    def render(self, state: UiViewState) -> None:
        self._update_window_size(state.state)
        if not state.replay_active:
            self._replay_repeater.release()
            self._replay_repeat_active = False
        self.state_text.value = (
            "Starting..."
            if self._resume_in_progress
            else "● REC"
            if state.state is ApplicationState.RECORDING
            else "● REPLAY"
            if state.state is ApplicationState.REPLAY
            else state.state_label
        )
        self.state_text.animate_opacity = 500 if state.state is ApplicationState.RECORDING else None
        self.state_text.opacity = (
            1.0
            if int(time.monotonic() * 2) % 2 == 0
            else 0.55
            if state.state is ApplicationState.RECORDING
            else 1.0
        )

        self.source_dropdown.options = [
            ft.DropdownOption(key=option.key, text=option.label) for option in state.input_options
        ]
        self.source_dropdown.value = state.selected_key
        self.source_dropdown.disabled = not state.controls.input_enabled

        self.refresh_button.content = "Discovering..." if state.discovering else "Refresh"
        self.refresh_button.disabled = not state.controls.refresh_enabled
        self.start_button.disabled = not state.controls.start_enabled
        setup_visible = state.state in (ApplicationState.IDLE, ApplicationState.STARTING)
        self.setup_section.visible = setup_visible
        self.about_button.disabled = state.state is not ApplicationState.IDLE
        self.session_section.visible = not setup_visible
        self.input_section.visible = setup_visible
        self.recording_section.visible = state.state is ApplicationState.RECORDING
        session_disabled = state.state is ApplicationState.STOPPING

        if state.state is ApplicationState.RECORDING:
            self._stable_session_mode = "recording"
        elif state.state is ApplicationState.REPLAY:
            self._stable_session_mode = "replay"
        stable_mode = self._stable_session_mode or "recording"
        self.mode_button.content = "Record" if stable_mode == "replay" else "Replay"
        session_disabled = session_disabled or self._resume_in_progress
        self.mode_button.disabled = session_disabled or state.state not in (
            ApplicationState.RECORDING,
            ApplicationState.REPLAY,
        )
        self.setup_button.disabled = session_disabled or state.state not in (
            ApplicationState.RECORDING,
            ApplicationState.REPLAY,
        )

        self._render_replay(state.replay)
        if self._resume_in_progress:
            self.replay_panel.visible = False
        self.replay_play_button.disabled = session_disabled or self.replay_play_button.disabled
        self.set_point_button.disabled = session_disabled or self.set_point_button.disabled
        self.replay_slider.disabled = session_disabled or self.replay_slider.disabled
        for gesture in (
            self.replay_back20_gesture,
            self.replay_back1_gesture,
            self.replay_forward1_gesture,
            self.replay_forward20_gesture,
        ):
            gesture.disabled = session_disabled

        metrics = state.metrics
        if metrics:
            drops = (
                f" · ⚠ Drops V:{metrics.video_drops} A:{metrics.audio_drops}"
                if metrics.has_drops
                else ""
            )
            self.recording_status_text.value = (
                f"Input {metrics.input_fps} · Rec {metrics.recording_fps} fps · "
                f"Seg {metrics.segments} · Buf {metrics.buffer}{drops}"
            )
        else:
            self.recording_status_text.value = ""

        status_message = None if state.discovering else state.status_message
        self.status_text.value = status_message or ""
        self.status_text.visible = bool(status_message)
        self.error_text.value = state.error_message or ""
        self.error_text.visible = bool(state.error_message)
        self.setup_status_text.value = status_message or ""
        self.setup_status_text.visible = bool(status_message)
        self.setup_error_text.value = state.error_message or ""
        self.setup_error_text.visible = bool(state.error_message)
        self.footer.visible = bool(status_message or state.error_message) and not setup_visible

    def _update_window_size(self, state: ApplicationState) -> None:
        if state in (ApplicationState.IDLE, ApplicationState.STARTING):
            self._resume_in_progress = False
            mode = "setup"
        elif state is ApplicationState.RECORDING:
            self._resume_in_progress = False
            self._stable_session_mode = "recording"
            mode = "recording"
        elif state is ApplicationState.REPLAY:
            if self._resume_in_progress:
                mode = "recording"
            else:
                self._stable_session_mode = "replay"
                mode = "replay"
        elif state is ApplicationState.RESUMING:
            self._resume_in_progress = True
            mode = "recording"
        elif state is ApplicationState.ERROR:
            self._resume_in_progress = False
            mode = "replay" if self._stable_session_mode == "replay" else "recording"
        elif self._stable_session_mode == "replay":
            mode = "replay"
        else:
            mode = "recording"
        if mode == self._window_mode:
            return
        self._window_mode = mode
        if not hasattr(self.page, "window"):
            return
        size = WINDOW_SIZES[mode]
        self.page.window.width, self.page.window.height = size

    def _render_replay(self, replay: ReplayView | None) -> None:
        self.replay_panel.visible = replay is not None
        if replay is None:
            self._seek_drag = SeekDrag()
            return

        if self._seek_drag.active:
            preview_ns = self._seek_drag.preview_ns or 0
            self.replay_position_text.value = (
                f"{format_duration_ns(preview_ns)} / {replay.duration_text}"
            )
        else:
            self.replay_position_text.value = f"{replay.position_text} / {replay.duration_text}"
            duration_seconds = replay.duration_ns / _NANOSECONDS_PER_SECOND
            self.replay_slider.max = duration_seconds if duration_seconds > 0 else 0
            self.replay_slider.value = replay.position_ns / _NANOSECONDS_PER_SECOND

        duration_seconds = replay.duration_ns / _NANOSECONDS_PER_SECOND
        self.replay_slider.disabled = duration_seconds <= 0 or self._replay_repeat_active
        self.replay_fps_text.value = f"{replay.fps_text} fps"
        cast(ft.Text, self.replay_play_button.content).value = "Play" if replay.paused else "Pause"
        self.replay_play_button.disabled = self._replay_repeat_active
        self.set_point_button.disabled = self._replay_repeat_active
        self.set_point_text.value = replay.set_point_text
        self.time_difference_text.value = replay.time_difference_text
        self.frame_difference_text.value = replay.frame_difference_text

    def _transport_button(
        self,
        label: str,
        on_click: Callable[[ft.Event], None] | None = None,
    ) -> ft.Container:
        return ft.Container(
            content=ft.Text(
                label,
                color=ft.Colors.ON_PRIMARY,
                size=14,
                text_align=ft.TextAlign.CENTER,
            ),
            width=REPLAY_TRANSPORT_BUTTON_WIDTH,
            height=REPLAY_TRANSPORT_BUTTON_HEIGHT,
            alignment=ft.Alignment.CENTER,
            bgcolor=ft.Colors.PRIMARY,
            padding=0,
            border_radius=ft.BorderRadius(top_left=4, top_right=4, bottom_left=4, bottom_right=4),
            on_click=on_click,
        )

    def _repeat_button(
        self, label: str, action: Callable[[], Awaitable[None]], interval: float
    ) -> tuple[ft.Container, ft.GestureDetector]:
        button = self._transport_button(label)
        gesture = ft.GestureDetector(
            content=button,
            on_tap=lambda _event: self._run_task(self._run_replay_action_async, action),
            on_long_press_start=lambda _event: self._start_replay_repeat(action, interval),
            on_long_press_end=lambda _event: self._stop_replay_repeat(),
            on_long_press_cancel=lambda _event: self._stop_replay_repeat(),
        )
        return button, gesture

    def _start_replay_repeat(self, action: Callable[[], Awaitable[None]], interval: float) -> None:
        self._replay_repeater.start(
            lambda: self._run_replay_action_async(action),
            interval=interval,
        )
        self._replay_repeat_active = True
        self._refresh_replay_controls()

    def _stop_replay_repeat(self) -> None:
        self._replay_repeater.release()
        self._replay_repeat_active = False
        self._refresh_replay_controls()

    def _refresh_replay_controls(self) -> None:
        disabled = self._replay_repeat_active
        self.replay_play_button.disabled = disabled
        self.set_point_button.disabled = disabled
        self.replay_slider.disabled = disabled

    async def _run_replay_action_async(self, action: Callable[[], Awaitable[None]]) -> None:
        if self.is_active:
            await action()

    # -- action handlers ---------------------------------------------------
    def _on_source_select(self, event: ft.Event) -> None:
        if not self.is_active:
            return
        self.session.select(self.source_dropdown.value)
        self._refresh_view()

    def _on_about(self, event: ft.Event) -> None:
        if not self.is_active:
            return
        if self.session.view_state().state is not ApplicationState.IDLE:
            return
        if self._about_process is not None:
            if self._about_process.poll() is None:
                return

        is_packaged = Path(sys.argv[0]).suffix.casefold() == ".exe"
        command = (
            [sys.executable, "--quickreplay-about"]
            if is_packaged
            else [sys.executable, "-m", "quickreplay.ui.about_window"]
        )
        self._about_process = subprocess.Popen(command)

    def _on_refresh(self, event: ft.Event) -> None:
        self._run_task(self._refresh)

    async def _refresh(self) -> None:
        await self._run_action(self.session.refresh)

    def _on_start(self, event: ft.Event) -> None:
        self._run_task(self._start)

    async def _start(self) -> None:
        await self._run_action(self.session.start_recording)

    def _on_mode_button(self, event: ft.Event) -> None:
        self._stop_replay_repeat()
        self._run_task(self._switch_session_mode)

    async def _switch_session_mode(self) -> None:
        state = self.session.view_state().state
        if state is ApplicationState.RECORDING:
            await self._run_action(self.session.request_replay)
        elif state is ApplicationState.REPLAY:
            self._resume_in_progress = True
            self._update_window_size(ApplicationState.RESUMING)
            self._refresh_view()
            try:
                await self._run_action(self.session.resume_recording)
            except Exception:
                self._resume_in_progress = False
                self._refresh_view()
                raise

    # -- replay handlers ---------------------------------------------------
    def _run_replay_action(self, action: str, frames: int | None = None) -> None:
        self._run_task(self._do_replay_action, action, frames)

    async def _do_replay_action(self, action: str, frames: int | None) -> None:
        if not self.is_active:
            return
        if action == "seek" and frames is not None:
            await self.session.seek_frames(frames)
        elif action == "step_forward":
            await self.session.step_forward()
        elif action == "step_backward":
            await self.session.step_backward()
        await self._render_and_update()

    def _on_play_pause(self, event: ft.Event) -> None:
        self._run_task(self._do_play_pause)

    async def _do_play_pause(self) -> None:
        await self._run_action(self.session.toggle_play_pause)

    def _on_set_point(self, event: ft.Event) -> None:
        self._run_task(self._do_set_point)

    async def _do_set_point(self) -> None:
        await self._run_action(self.session.set_replay_point)

    def _on_seek_start(self, event: ft.Event) -> None:
        if not self.is_active:
            return
        # While dragging, poll must not move the thumb.
        self._seek_drag.start(self.replay_slider.value or 0)

    def _on_seek_change(self, event: ft.Event) -> None:
        if not self.is_active:
            return
        # Preview only; no seek command is sent while dragging.
        self._seek_drag.update_preview(self.replay_slider.value or 0)
        self._refresh_view()

    def _on_seek_end(self, event: ft.Event) -> None:
        if not self.is_active:
            # A close during the drag discards the pending seek.
            return
        target_ns = self._seek_drag.end(self.replay_slider.value or 0)
        self._run_task(self._do_seek_absolute, target_ns)

    async def _do_seek_absolute(self, target_ns: int) -> None:
        await self._run_action(lambda: self.session.seek_absolute_ns(target_ns))

    # -- settings handlers -------------------------------------------------
    def _on_setup(self, event: ft.Event) -> None:
        self._stop_replay_repeat()
        self._run_task(self._stop_session)

    async def _stop_session(self) -> None:
        await self.session.stop_session()
        await self._render_and_update()

    def _populate_settings_fields(self) -> None:
        draft = self.session.settings_draft()
        self.settings_buffer_field.value = draft.buffer_duration_seconds
        self.settings_mpv_field.value = draft.mpv_executable
        self.settings_error_text.value = ""
        self.settings_error_text.visible = False

    def _settings_draft(self) -> SettingsDraft:
        return SettingsDraft(
            buffer_duration_seconds=self.settings_buffer_field.value or "",
            mpv_executable=self.settings_mpv_field.value or "",
        )

    def _on_settings_apply(self, event: ft.Event) -> None:
        self._run_task(self._apply_settings)

    async def _apply_settings(self) -> None:
        if not self.is_active:
            return
        draft = self._settings_draft()
        self.settings_apply_button.disabled = True
        self._update_page()
        try:
            result = await self.session.apply_settings(draft)
        finally:
            if self.is_active:
                self.settings_apply_button.disabled = False
        if not self.is_active:
            # A close began while the configuration was saving: the dialog is
            # gone with the session and the draft is discarded, never applied.
            return
        if result.ok:
            self.settings_error_text.value = ""
            self.settings_error_text.visible = False
            self.render(self.session.view_state())
        else:
            messages = [error.message for error in result.errors]
            if result.message:
                messages.insert(0, result.message)
            self.settings_error_text.value = "\n".join(messages)
            self.settings_error_text.visible = bool(self.settings_error_text.value)
        self._update_page()
