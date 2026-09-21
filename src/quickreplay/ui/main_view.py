"""Flet 1.0 controls for the QuickReplay main window.

The view is intentionally thin: it renders a
:class:`~quickreplay.ui.session.UiViewState` and forwards user actions to
:class:`~quickreplay.ui.session.UiSession`.  All application state lives in the
session; the view holds only transient widget state.
"""

import asyncio

import flet as ft

from quickreplay.ui.session import CAMERA_KIND, NDI_KIND, UiSession, UiViewState

POLL_INTERVAL_SECONDS = 0.1
_EMPTY = "—"


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

        self.status_text = ft.Text("", color=ft.Colors.BLUE_GREY)
        self.error_text = ft.Text("", color=ft.Colors.RED)

        self.control = ft.Column(
            controls=[
                ft.Row(
                    controls=[
                        ft.Text("QuickReplay", size=24, weight=ft.FontWeight.BOLD),
                        self.state_text,
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
                ft.Row(controls=[self.replay_button, self.resume_button]),
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
            self.render(self.session.view_state())
            self.page.update()
            await asyncio.sleep(POLL_INTERVAL_SECONDS)

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
        self.start_button.disabled = not state.controls.start_enabled
        self.replay_button.disabled = not state.controls.replay_enabled
        self.resume_button.disabled = not state.controls.resume_enabled
        self.replay_button.visible = not state.replay_active
        self.resume_button.visible = state.replay_active

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
