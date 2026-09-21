"""Flet 1.0 controls for the QuickReplay main window.

The view is intentionally thin: it renders a
:class:`~quickreplay.ui.session.UiViewState` and forwards user actions to
:class:`~quickreplay.ui.session.UiSession`.  All application state lives in the
session; the view holds only transient widget state.
"""

import asyncio
from dataclasses import dataclass
from decimal import Decimal

import flet as ft

from quickreplay.app.state import ApplicationState
from quickreplay.ui.presentation import format_duration_ns
from quickreplay.ui.session import (
    CAMERA_KIND,
    NDI_KIND,
    ReplayView,
    UiSession,
    UiViewState,
)
from quickreplay.ui.settings import SettingsDraft

POLL_INTERVAL_SECONDS = 0.1
POLL_INTERVAL_REPLAY_SECONDS = 0.05
_EMPTY = "—"
_NANOSECONDS_PER_SECOND = 1_000_000_000


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
        self._closing = False

        self.state_text = ft.Text("", weight=ft.FontWeight.BOLD)
        self.kind_button = ft.SegmentedButton(
            segments=[
                ft.Segment(value=NDI_KIND, label=ft.Text("NDI")),
                ft.Segment(value=CAMERA_KIND, label=ft.Text("Camera")),
            ],
            selected=[NDI_KIND],
            on_change=self._on_kind_change,
        )
        self.source_dropdown = ft.Dropdown(
            label="Input", options=[], width=380, on_select=self._on_source_select
        )
        self.backend_dropdown = ft.Dropdown(
            label="Backend", options=[], width=160, on_select=self._on_backend_select
        )
        self.refresh_button = ft.FilledButton(content="Refresh", on_click=self._on_refresh)
        self.start_button = ft.FilledButton(content="Start Recording", on_click=self._on_start)
        self.replay_button = ft.FilledButton(content="Replay", on_click=self._on_replay)
        self.resume_button = ft.FilledButton(content="Resume Recording", on_click=self._on_resume)

        self.stream_text = ft.Text(_EMPTY)
        self.audio_text = ft.Text(_EMPTY)
        self.input_fps_text = ft.Text(_EMPTY)
        self.recording_fps_text = ft.Text(_EMPTY)
        self.buffer_text = ft.Text(_EMPTY)
        self.buffer_bar = ft.ProgressBar(value=0)
        self.segments_text = ft.Text(_EMPTY)
        self.drops_text = ft.Text(_EMPTY)
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
        self.replay_play_button = ft.FilledButton(content="Play", on_click=self._on_play_pause)
        self.replay_back20_button = ft.FilledButton(
            content="-20f", on_click=lambda _event: self._run_replay_action("seek", -20)
        )
        self.replay_back1_button = ft.FilledButton(
            content="-1f", on_click=lambda _event: self._run_replay_action("step_backward")
        )
        self.replay_forward1_button = ft.FilledButton(
            content="+1f", on_click=lambda _event: self._run_replay_action("step_forward")
        )
        self.replay_forward20_button = ft.FilledButton(
            content="+20f", on_click=lambda _event: self._run_replay_action("seek", 20)
        )
        self.set_point_text = ft.Text(_EMPTY)
        self.time_difference_text = ft.Text(_EMPTY)
        self.frame_difference_text = ft.Text(_EMPTY)
        self.set_point_button = ft.FilledButton(content="Set Point", on_click=self._on_set_point)
        self.replay_panel = ft.Column(
            controls=[
                ft.Text("Replay", weight=ft.FontWeight.BOLD),
                ft.Row(controls=[self.replay_position_text, ft.Text("|"), self.replay_fps_text]),
                self.replay_slider,
                ft.Row(
                    controls=[
                        self.replay_back20_button,
                        self.replay_back1_button,
                        self.replay_play_button,
                        self.replay_forward1_button,
                        self.replay_forward20_button,
                    ]
                ),
                ft.Row(controls=[ft.Text("Set Point:"), self.set_point_text]),
                ft.Row(controls=[ft.Text("Difference:"), self.time_difference_text]),
                ft.Row(controls=[ft.Text("Frames:"), self.frame_difference_text]),
                ft.Row(
                    controls=[self.set_point_button, self.resume_button],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                ),
            ],
            spacing=10,
            visible=False,
        )

        # Settings dialog (Flet-independent draft + validation live in the session).
        self._settings_camera_available = False
        self.settings_header_button = ft.FilledButton(
            content="Settings", on_click=self._on_settings_open
        )
        self.settings_camera_label = ft.Text("", italic=True, color=ft.Colors.BLUE_GREY)
        self.settings_camera_hint = ft.Text("Select a camera input to edit its capture mode.")
        self.settings_explicit_checkbox = ft.Checkbox(
            label="Use explicit camera mode",
            value=False,
            on_change=self._on_settings_explicit_change,
        )
        self.settings_width_field = ft.TextField(label="Width", width=150)
        self.settings_height_field = ft.TextField(label="Height", width=150)
        self.settings_numerator_field = ft.TextField(label="Numerator", width=150)
        self.settings_denominator_field = ft.TextField(label="Denominator", width=150)
        self.settings_buffer_field = ft.TextField(label="Buffer duration", width=180)
        self.settings_mpv_field = ft.TextField(label="mpv executable", width=380)
        self.settings_error_text = ft.Text("", color=ft.Colors.RED)
        self.settings_cancel_button = ft.TextButton(
            content="Cancel", on_click=self._on_settings_cancel
        )
        self.settings_apply_button = ft.FilledButton(
            content="Apply", on_click=self._on_settings_apply
        )
        self.settings_dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("Settings"),
            content=ft.Column(
                controls=[
                    ft.Text("Camera", weight=ft.FontWeight.BOLD),
                    self.settings_camera_label,
                    self.settings_explicit_checkbox,
                    self.settings_camera_hint,
                    ft.Row(controls=[self.settings_width_field, self.settings_height_field]),
                    ft.Row(
                        controls=[
                            self.settings_numerator_field,
                            ft.Text("/"),
                            self.settings_denominator_field,
                        ]
                    ),
                    ft.Divider(),
                    ft.Text("Recording", weight=ft.FontWeight.BOLD),
                    ft.Row(controls=[self.settings_buffer_field, ft.Text("seconds")]),
                    ft.Text("Restart required after changing", italic=True),
                    ft.Divider(),
                    ft.Text("Replay", weight=ft.FontWeight.BOLD),
                    self.settings_mpv_field,
                    ft.Text("Restart required after changing", italic=True),
                    self.settings_error_text,
                ],
                spacing=8,
                tight=True,
                width=460,
                scroll=ft.ScrollMode.AUTO,
            ),
            actions=[self.settings_cancel_button, self.settings_apply_button],
            actions_alignment=ft.MainAxisAlignment.END,
        )

        self.status_text = ft.Text("", color=ft.Colors.BLUE_GREY)
        self.error_text = ft.Text("", color=ft.Colors.RED)

        self.control = ft.Column(
            controls=[
                ft.Row(
                    controls=[
                        ft.Text("QuickReplay", size=24, weight=ft.FontWeight.BOLD),
                        ft.Row(controls=[self.state_text, self.settings_header_button]),
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                ),
                ft.Divider(),
                ft.Text("Input", weight=ft.FontWeight.BOLD),
                self.kind_button,
                ft.Row(controls=[self.source_dropdown, self.refresh_button]),
                self.backend_dropdown,
                self.start_button,
                ft.Divider(),
                ft.Text("Recording", weight=ft.FontWeight.BOLD),
                self.stream_text,
                self.audio_text,
                ft.Row(controls=[ft.Text("Input FPS"), self.input_fps_text]),
                ft.Row(controls=[ft.Text("Recording FPS"), self.recording_fps_text]),
                ft.Row(controls=[ft.Text("Buffer"), self.buffer_text]),
                self.buffer_bar,
                ft.Row(controls=[ft.Text("Segments"), self.segments_text]),
                ft.Row(controls=[ft.Text("Drops"), self.drops_text]),
                ft.Row(controls=[self.replay_button]),
                ft.Divider(),
                self.replay_panel,
                ft.Divider(),
                self.status_text,
                self.error_text,
            ],
            spacing=10,
        )

    # -- lifecycle ---------------------------------------------------------
    async def start(self) -> None:
        await self.session.start()
        self.render(self.session.view_state())
        self.page.update()

    async def poll_loop(self) -> None:
        while not self._closing:
            try:
                await self.session.poll()
            except Exception as exc:  # noqa: BLE001 - surface poll failures in the UI
                self.session.note_error(f"UI poll failed: {exc}")
            state = self.session.view_state()
            self.render(state)
            self.page.update()
            interval = (
                POLL_INTERVAL_REPLAY_SECONDS
                if state.state is ApplicationState.REPLAY
                else POLL_INTERVAL_SECONDS
            )
            await asyncio.sleep(interval)

    def on_window_event(self, event: ft.WindowEvent) -> None:
        if getattr(event, "type", None) == ft.WindowEventType.CLOSE:
            self.page.run_task(self.close)

    async def close(self) -> None:
        if self._closing:
            return
        self._closing = True
        try:
            await self.session.shutdown()
        finally:
            await self.page.window.destroy()

    # -- rendering ---------------------------------------------------------
    def render(self, state: UiViewState) -> None:
        self.state_text.value = state.state_label

        self.kind_button.selected = [state.input_kind]
        self.kind_button.disabled = not state.controls.input_enabled

        self.source_dropdown.options = [
            ft.DropdownOption(key=option.key, text=option.label) for option in state.input_options
        ]
        self.source_dropdown.value = state.selected_key
        self.source_dropdown.disabled = not state.controls.input_enabled

        self.backend_dropdown.options = [
            ft.DropdownOption(key=backend, text=backend) for backend in state.camera_backend_options
        ]
        self.backend_dropdown.value = state.camera_backend
        self.backend_dropdown.visible = state.show_camera_backend
        self.backend_dropdown.disabled = not state.controls.input_enabled

        self.refresh_button.content = "Discovering..." if state.discovering else "Refresh"
        self.refresh_button.disabled = not state.controls.refresh_enabled
        self.settings_header_button.disabled = not state.controls.settings_enabled
        self.start_button.disabled = not state.controls.start_enabled
        self.replay_button.disabled = not state.controls.replay_enabled
        self.replay_button.visible = not state.replay_active

        self._render_replay(state.replay)

        self.stream_text.value = state.stream_text
        self.audio_text.value = state.audio_text
        metrics = state.metrics
        self.input_fps_text.value = metrics.input_fps if metrics else _EMPTY
        self.recording_fps_text.value = metrics.recording_fps if metrics else _EMPTY
        self.buffer_text.value = metrics.buffer if metrics else _EMPTY
        self.buffer_bar.value = metrics.buffer_fraction if metrics else 0
        self.segments_text.value = metrics.segments if metrics else _EMPTY
        self.drops_text.value = metrics.drops if metrics else _EMPTY

        self.status_text.value = state.status_message or ""
        self.status_text.visible = bool(state.status_message)
        self.error_text.value = state.error_message or ""
        self.error_text.visible = bool(state.error_message)

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
        self.replay_slider.disabled = duration_seconds <= 0 or replay.action_pending
        self.replay_fps_text.value = f"{replay.fps_text} fps"
        self.replay_play_button.content = "Play" if replay.paused else "Pause"
        for button in (
            self.replay_back20_button,
            self.replay_back1_button,
            self.replay_play_button,
            self.replay_forward1_button,
            self.replay_forward20_button,
            self.set_point_button,
            self.resume_button,
        ):
            button.disabled = replay.action_pending
        self.set_point_text.value = replay.set_point_text
        self.time_difference_text.value = replay.time_difference_text
        self.frame_difference_text.value = replay.frame_difference_text

    # -- action handlers ---------------------------------------------------
    def _on_kind_change(self, event: ft.Event) -> None:
        selected = self.kind_button.selected
        if selected:
            self.page.run_task(self._change_kind, next(iter(selected)))

    async def _change_kind(self, kind: str) -> None:
        await self.session.set_input_kind(kind)
        self.render(self.session.view_state())
        self.page.update()

    def _on_source_select(self, event: ft.Event) -> None:
        self.session.select(self.source_dropdown.value)
        self.render(self.session.view_state())
        self.page.update()

    def _on_backend_select(self, event: ft.Event) -> None:
        self.page.run_task(self._change_backend, self.backend_dropdown.value)

    async def _change_backend(self, backend: str | None) -> None:
        if backend:
            await self.session.set_camera_backend(backend)
        self.render(self.session.view_state())
        self.page.update()

    def _on_refresh(self, event: ft.Event) -> None:
        self.page.run_task(self._refresh)

    async def _refresh(self) -> None:
        await self.session.refresh()
        self.render(self.session.view_state())
        self.page.update()

    def _on_start(self, event: ft.Event) -> None:
        self.page.run_task(self._start)

    async def _start(self) -> None:
        await self.session.start_recording()
        self.render(self.session.view_state())
        self.page.update()

    def _on_replay(self, event: ft.Event) -> None:
        self.page.run_task(self._replay)

    async def _replay(self) -> None:
        await self.session.request_replay()
        self.render(self.session.view_state())
        self.page.update()

    def _on_resume(self, event: ft.Event) -> None:
        self.page.run_task(self._resume)

    async def _resume(self) -> None:
        await self.session.resume_recording()
        self.render(self.session.view_state())
        self.page.update()

    # -- replay handlers ---------------------------------------------------
    def _run_replay_action(self, action: str, frames: int | None = None) -> None:
        self.page.run_task(self._do_replay_action, action, frames)

    async def _do_replay_action(self, action: str, frames: int | None) -> None:
        if action == "seek" and frames is not None:
            await self.session.seek_frames(frames)
        elif action == "step_forward":
            await self.session.step_forward()
        elif action == "step_backward":
            await self.session.step_backward()
        self.render(self.session.view_state())
        self.page.update()

    def _on_play_pause(self, event: ft.Event) -> None:
        self.page.run_task(self._do_play_pause)

    async def _do_play_pause(self) -> None:
        await self.session.toggle_play_pause()
        self.render(self.session.view_state())
        self.page.update()

    def _on_set_point(self, event: ft.Event) -> None:
        self.page.run_task(self._do_set_point)

    async def _do_set_point(self) -> None:
        await self.session.set_replay_point()
        self.render(self.session.view_state())
        self.page.update()

    def _on_seek_start(self, event: ft.Event) -> None:
        # While dragging, poll must not move the thumb.
        self._seek_drag.start(self.replay_slider.value or 0)

    def _on_seek_change(self, event: ft.Event) -> None:
        # Preview only; no seek command is sent while dragging.
        self._seek_drag.update_preview(self.replay_slider.value or 0)
        self.render(self.session.view_state())
        self.page.update()

    def _on_seek_end(self, event: ft.Event) -> None:
        target_ns = self._seek_drag.end(self.replay_slider.value or 0)
        self.page.run_task(self._do_seek_absolute, target_ns)

    async def _do_seek_absolute(self, target_ns: int) -> None:
        await self.session.seek_absolute_ns(target_ns)
        self.render(self.session.view_state())
        self.page.update()

    # -- settings handlers -------------------------------------------------
    def _on_settings_open(self, event: ft.Event) -> None:
        self._populate_settings_dialog()
        self.page.show_dialog(self.settings_dialog)

    def _populate_settings_dialog(self) -> None:
        draft = self.session.settings_draft()
        self._settings_camera_available = draft.camera_available
        self.settings_explicit_checkbox.value = draft.use_explicit_camera_mode
        self.settings_width_field.value = draft.camera_width
        self.settings_height_field.value = draft.camera_height
        self.settings_numerator_field.value = draft.camera_fps_numerator
        self.settings_denominator_field.value = draft.camera_fps_denominator
        self.settings_buffer_field.value = draft.buffer_duration_seconds
        self.settings_mpv_field.value = draft.mpv_executable
        self.settings_camera_label.value = (
            f"Editing: {draft.camera_label}" if draft.camera_available else ""
        )
        self.settings_error_text.value = ""
        self._apply_settings_field_state()
        self.page.update()

    def _on_settings_explicit_change(self, event: ft.Event) -> None:
        self._apply_settings_field_state()
        self.page.update()

    def _apply_settings_field_state(self) -> None:
        available = self._settings_camera_available
        explicit = bool(self.settings_explicit_checkbox.value)
        self.settings_explicit_checkbox.disabled = not available
        self.settings_camera_hint.visible = not available
        for field in (
            self.settings_width_field,
            self.settings_height_field,
            self.settings_numerator_field,
            self.settings_denominator_field,
        ):
            field.disabled = not (available and explicit)

    def _settings_draft(self) -> SettingsDraft:
        return SettingsDraft(
            use_explicit_camera_mode=bool(self.settings_explicit_checkbox.value),
            camera_width=self.settings_width_field.value or "",
            camera_height=self.settings_height_field.value or "",
            camera_fps_numerator=self.settings_numerator_field.value or "",
            camera_fps_denominator=self.settings_denominator_field.value or "",
            buffer_duration_seconds=self.settings_buffer_field.value or "",
            mpv_executable=self.settings_mpv_field.value or "",
            camera_available=self._settings_camera_available,
        )

    def _on_settings_cancel(self, event: ft.Event) -> None:
        # Cancel discards the draft: nothing is saved and the session config is
        # untouched.  The next open repopulates from the persisted config.
        self.page.pop_dialog()

    def _on_settings_apply(self, event: ft.Event) -> None:
        self.page.run_task(self._apply_settings)

    async def _apply_settings(self) -> None:
        draft = self._settings_draft()
        self.settings_apply_button.disabled = True
        self.settings_cancel_button.disabled = True
        self.page.update()
        try:
            result = await self.session.apply_settings(draft)
        finally:
            self.settings_apply_button.disabled = False
            self.settings_cancel_button.disabled = False
        if result.ok:
            self.page.pop_dialog()
            self.render(self.session.view_state())
        else:
            messages = [error.message for error in result.errors]
            if result.message:
                messages.insert(0, result.message)
            self.settings_error_text.value = "\n".join(messages)
        self.page.update()
