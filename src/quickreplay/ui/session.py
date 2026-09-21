"""Flet-independent UI session logic.

:class:`UiSession` holds the UI's own state (selected input, discovery
correlation, transient status) and drives the application through
:class:`~quickreplay.ui.bridge.ApplicationUiBridge`.  It contains no Flet
imports so it can be tested headlessly.
"""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from typing import Protocol
from uuid import UUID

from quickreplay.app.state import ApplicationState
from quickreplay.application.events import (
    ApplicationError,
    ApplicationEvent,
    InputsChanged,
    RecordingStarted,
)
from quickreplay.application.models import ApplicationSnapshot
from quickreplay.configuration.errors import ConfigurationError
from quickreplay.configuration.models import QuickReplayConfig
from quickreplay.configuration.store import ConfigurationStore
from quickreplay.input.models import (
    CameraInputConfig,
    CameraInputDescriptor,
    CameraMode,
    InputConfig,
    InputDescriptor,
    NdiInputConfig,
    NdiInputDescriptor,
)
from quickreplay.replay.errors import MpvProcessExitedError
from quickreplay.replay.models import SetPoint
from quickreplay.ui.presentation import (
    ControlState,
    MetricsView,
    camera_backend_options,
    control_state,
    format_audio,
    format_duration_ns,
    format_fps,
    format_signed_duration_ns,
    format_signed_frames,
    format_stream_info,
    metrics_view,
    state_label,
)
from quickreplay.ui.settings import (
    SettingsApplyResult,
    SettingsDraft,
    apply_message,
    build_settings_config,
    draft_from_config,
    restart_required,
)

NDI_KIND = "ndi"
CAMERA_KIND = "camera"


class BridgeLike(Protocol):
    """The async bridge operations the UI session needs."""

    async def start(self) -> None: ...

    async def start_recording(self, input_config: InputConfig) -> None: ...

    async def discover_inputs(self, *, camera_backend: str = "any") -> UUID: ...

    async def request_replay(self) -> UUID: ...

    async def resume_recording(self) -> UUID: ...

    async def poll(self, timeout: float = 0.0) -> tuple[ApplicationEvent, ...]: ...

    async def snapshot(self) -> ApplicationSnapshot: ...

    async def shutdown(self) -> None: ...

    async def close(self) -> None: ...

    # -- replay delegate ---------------------------------------------------
    async def play(self) -> None: ...

    async def pause(self) -> None: ...

    async def is_paused(self) -> bool: ...

    async def step_forward(self) -> None: ...

    async def step_backward(self) -> None: ...

    async def seek_frames(self, frames: int) -> None: ...

    async def seek_absolute_ns(self, position_ns: int) -> None: ...

    async def replay_position_ns(self) -> int: ...

    async def set_point(self) -> SetPoint: ...

    async def time_difference_ns(self, point: SetPoint) -> int: ...

    async def frame_difference(self, point: SetPoint) -> int: ...


@dataclass(frozen=True, slots=True)
class InputOption:
    """A selectable discovered input."""

    key: str
    kind: str
    label: str
    descriptor: InputDescriptor


@dataclass(frozen=True, slots=True)
class ReplayView:
    """Display-ready replay playback state (only populated while replaying)."""

    position_ns: int
    duration_ns: int
    paused: bool
    position_text: str
    duration_text: str
    fps_text: str
    set_point_text: str
    time_difference_text: str
    frame_difference_text: str
    has_set_point: bool
    action_pending: bool


@dataclass(frozen=True, slots=True)
class UiViewState:
    """Everything the Flet view needs to render one frame."""

    state: ApplicationState
    state_label: str
    stream_text: str
    audio_text: str
    metrics: MetricsView | None
    controls: ControlState
    status_message: str | None
    error_message: str | None
    replay_active: bool
    replay: ReplayView | None
    input_options: tuple[InputOption, ...]
    selected_key: str | None
    input_kind: str
    show_camera_backend: bool
    camera_backend: str
    camera_backend_options: tuple[str, ...]
    discovering: bool


def _option_key(descriptor: InputDescriptor) -> str:
    if isinstance(descriptor, NdiInputDescriptor):
        return f"{NDI_KIND}:{descriptor.source_name}"
    return f"{CAMERA_KIND}:{descriptor.device_index}"


def _option_label(descriptor: InputDescriptor) -> str:
    if isinstance(descriptor, NdiInputDescriptor):
        return descriptor.source_name
    return f"{descriptor.device_name} (#{descriptor.device_index})"


def _config_matches(configured: InputConfig, descriptor: InputDescriptor) -> bool:
    if isinstance(configured, NdiInputConfig) and isinstance(descriptor, NdiInputDescriptor):
        return configured.source_name == descriptor.source_name
    if isinstance(configured, CameraInputConfig) and isinstance(descriptor, CameraInputDescriptor):
        return configured.device_index == descriptor.device_index
    return False


class UiSession:
    """UI state and actions over an :class:`ApplicationUiBridge`."""

    def __init__(
        self,
        bridge: BridgeLike,
        store: ConfigurationStore,
        config: QuickReplayConfig,
    ) -> None:
        self._bridge = bridge
        self._store = store
        self._config = config

        self._snapshot = ApplicationSnapshot(state=ApplicationState.STARTING)
        self._descriptors: tuple[InputDescriptor, ...] = ()
        self._input_kind = self._initial_kind(config.input)
        self._camera_backend = self._initial_backend(config.input)
        self._selected_key: str | None = None
        self._pending_discovery_id: UUID | None = None
        self._discovering = False
        self._pending_start_input: InputConfig | None = None
        self._status: str | None = None
        self._error: str | None = None

        self._replay_position_ns: int | None = None
        self._replay_paused: bool | None = None
        self._set_point: SetPoint | None = None
        self._time_difference_ns: int | None = None
        self._frame_difference: int | None = None
        self._replay_action_pending = False
        self._settings_applying = False
        self._shutdown_task: asyncio.Task[None] | None = None
        self._shutdown_complete = False

    # -- queries -----------------------------------------------------------
    @property
    def config(self) -> QuickReplayConfig:
        return self._config

    @property
    def input_kind(self) -> str:
        return self._input_kind

    def view_state(self) -> UiViewState:
        stream_info = self._snapshot.stream_info
        has_selection = self.selected_option() is not None
        return UiViewState(
            state=self._snapshot.state,
            state_label=state_label(self._snapshot.state),
            stream_text=format_stream_info(stream_info),
            audio_text=format_audio(stream_info),
            metrics=metrics_view(
                self._snapshot.metrics,
                buffer_max_seconds=self._config.recording.buffer_duration_seconds,
            ),
            controls=control_state(
                self._snapshot.state,
                has_selection=has_selection,
                discovering=self._discovering,
            ),
            status_message=self._status,
            error_message=self._error or self._snapshot.error_message,
            replay_active=self._snapshot.state == ApplicationState.REPLAY,
            replay=self._replay_view(),
            input_options=self._options(),
            selected_key=self._selected_key,
            input_kind=self._input_kind,
            show_camera_backend=self._input_kind == CAMERA_KIND,
            camera_backend=self._camera_backend,
            camera_backend_options=camera_backend_options(),
            discovering=self._discovering,
        )

    def selected_option(self) -> InputOption | None:
        for option in self._options():
            if option.key == self._selected_key:
                return option
        return None

    def build_input_config(self) -> InputConfig | None:
        """Build the domain input config for the current selection."""
        option = self.selected_option()
        if option is None:
            return None
        descriptor = option.descriptor
        if isinstance(descriptor, NdiInputDescriptor):
            return NdiInputConfig(descriptor.source_name)
        return CameraInputConfig(
            device_name=descriptor.device_name,
            device_index=descriptor.device_index,
            backend=self._camera_backend,
            mode=self._saved_camera_mode(descriptor),
        )

    # -- actions -----------------------------------------------------------
    async def start(self) -> None:
        await self._bridge.start()
        await self.refresh()

    async def refresh(self) -> None:
        self._discovering = True
        self._status = "Discovering..."
        self._pending_discovery_id = await self._bridge.discover_inputs(
            camera_backend=self._camera_backend
        )

    async def poll(self) -> None:
        events = await self._bridge.poll()
        for event in events:
            self._handle_event(event)
        previous_state = self._snapshot.state
        self._snapshot = await self._bridge.snapshot()
        if self._snapshot.state in (ApplicationState.IDLE, ApplicationState.ERROR):
            self._pending_start_input = None
        if self._snapshot.state == ApplicationState.REPLAY:
            if previous_state != ApplicationState.REPLAY:
                self._reset_replay_state()
            await self.refresh_replay_status()
        elif previous_state == ApplicationState.REPLAY:
            # Leaving replay clears the transient replay UI state.
            self._reset_replay_state()
            if self._snapshot.state != ApplicationState.ERROR:
                self._error = None

    async def set_input_kind(self, kind: str) -> None:
        if kind not in (NDI_KIND, CAMERA_KIND) or kind == self._input_kind:
            return
        self._input_kind = kind
        self._selected_key = None
        self._resolve_selection()
        if kind == CAMERA_KIND:
            await self.refresh()

    async def set_camera_backend(self, backend: str) -> None:
        if backend == self._camera_backend:
            return
        self._camera_backend = backend
        self._selected_key = None
        self._resolve_selection()
        await self.refresh()

    def select(self, key: str | None) -> None:
        self._selected_key = key

    async def start_recording(self) -> None:
        config = self.build_input_config()
        if config is None:
            return
        self._pending_start_input = config
        await self._bridge.start_recording(config)

    async def request_replay(self) -> None:
        await self._bridge.request_replay()

    async def resume_recording(self) -> None:
        await self._bridge.resume_recording()

    async def shutdown(self) -> None:
        """Shut the application down exactly once.

        Repeated and concurrent calls share a single shutdown task, so the
        bridge/controller/worker are never torn down twice.
        """
        if self._shutdown_complete:
            return
        if self._shutdown_task is None:
            self._shutdown_task = asyncio.ensure_future(self._shutdown_bridge())
        await self._shutdown_task
        self._shutdown_complete = True

    async def _shutdown_bridge(self) -> None:
        await self._bridge.shutdown()
        await self._bridge.close()

    def note_error(self, message: str) -> None:
        """Record a UI-side error (for example a failed poll iteration)."""
        self._error = message

    # -- settings ----------------------------------------------------------
    def settings_draft(self) -> SettingsDraft:
        """Snapshot the persisted config and current selection into a draft."""
        return draft_from_config(self._config, camera_input=self.build_input_config())

    async def apply_settings(self, draft: SettingsDraft) -> SettingsApplyResult:
        """Validate and persist *draft*, replacing the session config on success.

        The candidate configuration is written first and the in-memory config is
        only replaced after the store write succeeded, so a failed save never
        leaves the session pointing at an unsaved configuration.  Camera mode
        changes are picked up by :meth:`build_input_config` for the next start.
        """
        if self._settings_applying:
            return SettingsApplyResult(ok=False, message="Settings are already being applied")
        self._settings_applying = True
        try:
            validation = build_settings_config(
                draft, self._config, camera_input=self.build_input_config()
            )
            if validation.config is None:
                return SettingsApplyResult(ok=False, errors=validation.errors)
            candidate = validation.config
            restart = restart_required(self._config, candidate)
            input_changed = self._config.input != candidate.input
            try:
                await asyncio.to_thread(self._store.save, candidate)
            except ConfigurationError as exc:
                return SettingsApplyResult(ok=False, message=f"Could not save settings: {exc}")
            self._config = candidate
            self._status = apply_message(restart=restart, input_changed=input_changed)
            return SettingsApplyResult(ok=True, restart_required=restart, message=self._status)
        finally:
            self._settings_applying = False

    # -- replay actions ----------------------------------------------------
    async def toggle_play_pause(self) -> None:
        """Toggle using the core pause state as the source of truth."""

        async def action() -> None:
            if await self._bridge.is_paused():
                await self._bridge.play()
            else:
                await self._bridge.pause()

        await self._run_replay_action(action)

    async def step_backward(self) -> None:
        await self._run_replay_action(self._bridge.step_backward)

    async def step_forward(self) -> None:
        await self._run_replay_action(self._bridge.step_forward)

    async def seek_frames(self, frames: int) -> None:
        await self._run_replay_action(lambda: self._bridge.seek_frames(frames))

    async def seek_absolute_ns(self, position_ns: int) -> None:
        await self._run_replay_action(lambda: self._bridge.seek_absolute_ns(position_ns))

    async def set_replay_point(self) -> None:
        async def action() -> None:
            self._set_point = await self._bridge.set_point()

        await self._run_replay_action(action)

    async def refresh_replay_status(self) -> None:
        """Refresh position, pause state and differences while replaying."""
        if self._snapshot.state != ApplicationState.REPLAY:
            return
        try:
            self._replay_position_ns = await self._bridge.replay_position_ns()
            self._replay_paused = await self._bridge.is_paused()
            if self._set_point is not None:
                self._time_difference_ns = await self._bridge.time_difference_ns(self._set_point)
                self._frame_difference = await self._bridge.frame_difference(self._set_point)
        except MpvProcessExitedError:
            # The application controller already treats this as the replay
            # ending; do not surface it as a UI error.
            pass
        except Exception as exc:  # noqa: BLE001 - transient replay control error
            self._error = f"Replay control failed: {exc}"

    async def _run_replay_action(self, action: Callable[[], Awaitable[None]]) -> None:
        if self._replay_action_pending:
            return
        self._replay_action_pending = True
        try:
            await action()
        except MpvProcessExitedError:
            pass
        except Exception as exc:  # noqa: BLE001 - transient replay control error
            self._error = f"Replay control failed: {exc}"
        finally:
            self._replay_action_pending = False
            await self.refresh_replay_status()

    # -- internals ---------------------------------------------------------
    def _reset_replay_state(self) -> None:
        self._replay_position_ns = None
        self._replay_paused = None
        self._set_point = None
        self._time_difference_ns = None
        self._frame_difference = None

    def _replay_view(self) -> ReplayView | None:
        if self._snapshot.state != ApplicationState.REPLAY:
            return None
        asset = self._snapshot.replay_asset
        duration_ns = asset.duration_ns if asset is not None else 0
        position_ns = self._replay_position_ns if self._replay_position_ns is not None else 0
        set_point = self._set_point
        return ReplayView(
            position_ns=position_ns,
            duration_ns=duration_ns,
            paused=bool(self._replay_paused),
            position_text=format_duration_ns(position_ns),
            duration_text=format_duration_ns(duration_ns),
            fps_text=format_fps(asset.fps) if asset is not None else "—",
            set_point_text=format_duration_ns(set_point.position_ns) if set_point else "—",
            time_difference_text=(
                format_signed_duration_ns(self._time_difference_ns)
                if self._time_difference_ns is not None
                else "—"
            ),
            frame_difference_text=(
                format_signed_frames(self._frame_difference)
                if self._frame_difference is not None
                else "—"
            ),
            has_set_point=set_point is not None,
            action_pending=self._replay_action_pending,
        )

    # -- event handling ----------------------------------------------------
    def _handle_event(self, event: ApplicationEvent) -> None:
        if isinstance(event, InputsChanged):
            self._handle_inputs(event)
        elif isinstance(event, RecordingStarted):
            self._persist_started_input()
        elif isinstance(event, ApplicationError):
            self._error = event.message

    def _handle_inputs(self, event: InputsChanged) -> None:
        if event.request_id != self._pending_discovery_id:
            return  # stale discovery result
        self._pending_discovery_id = None
        self._discovering = False
        self._status = None
        self._descriptors = event.inputs
        self._resolve_selection()

    def _persist_started_input(self) -> None:
        started = self._pending_start_input
        self._pending_start_input = None
        if started is None:
            return
        updated = replace(self._config, input=started)
        try:
            self._store.save(updated)
        except ConfigurationError as exc:
            self._status = f"Recording started, but configuration could not be saved: {exc}"
            return
        self._config = updated

    def _resolve_selection(self) -> None:
        options = self._options()
        configured = self._config.input
        if configured is not None:
            for option in options:
                if _config_matches(configured, option.descriptor):
                    self._selected_key = option.key
                    return
            self._selected_key = None
            self._status = "Configured input is not currently available"
            return
        self._selected_key = options[0].key if options else None

    def _options(self) -> tuple[InputOption, ...]:
        return tuple(
            InputOption(
                key=_option_key(descriptor),
                kind=self._input_kind,
                label=_option_label(descriptor),
                descriptor=descriptor,
            )
            for descriptor in self._descriptors
            if self._descriptor_kind(descriptor) == self._input_kind
        )

    def _descriptor_kind(self, descriptor: InputDescriptor) -> str:
        return CAMERA_KIND if isinstance(descriptor, CameraInputDescriptor) else NDI_KIND

    def _saved_camera_mode(self, descriptor: CameraInputDescriptor) -> CameraMode | None:
        configured = self._config.input
        if (
            isinstance(configured, CameraInputConfig)
            and configured.device_index == descriptor.device_index
        ):
            return configured.mode
        return None

    def _initial_kind(self, configured: InputConfig | None) -> str:
        return CAMERA_KIND if isinstance(configured, CameraInputConfig) else NDI_KIND

    def _initial_backend(self, configured: InputConfig | None) -> str:
        if isinstance(configured, CameraInputConfig):
            return configured.backend
        return "any"
