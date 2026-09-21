"""Flet-independent UI session logic.

:class:`UiSession` holds the UI's own state (selected input, discovery
correlation, transient status) and drives the application through
:class:`~quickreplay.ui.bridge.ApplicationUiBridge`.  It contains no Flet
imports so it can be tested headlessly.
"""

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
from quickreplay.ui.presentation import (
    ControlState,
    MetricsView,
    camera_backend_options,
    control_state,
    format_audio,
    format_stream_info,
    metrics_view,
    state_label,
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


@dataclass(frozen=True, slots=True)
class InputOption:
    """A selectable discovered input."""

    key: str
    kind: str
    label: str
    descriptor: InputDescriptor


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
        self._snapshot = await self._bridge.snapshot()
        if self._snapshot.state in (ApplicationState.IDLE, ApplicationState.ERROR):
            self._pending_start_input = None

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
        await self._bridge.shutdown()
        await self._bridge.close()

    def note_error(self, message: str) -> None:
        """Record a UI-side error (for example a failed poll iteration)."""
        self._error = message

    # -- internals ---------------------------------------------------------
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
