"""Recorder worker runtime: the command loop running inside the worker process.

``RecorderWorkerRuntime`` owns the recording pipeline lifecycle, the replay
asset lifecycle, worker state and event emission.  It receives picklable
``WorkerCommand`` values and emits picklable ``WorkerEvent`` values; no frames
or native objects cross this boundary.
"""

import queue
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Protocol
from uuid import UUID

from quickreplay.input.models import InputConfig, InputDescriptor
from quickreplay.recording.commands import (
    ChangeInput,
    DiscoverInputs,
    PrepareReplay,
    ResumeRecording,
    Shutdown,
    StartRecording,
    WorkerCommand,
)
from quickreplay.recording.events import (
    InputsDiscovered,
    RecordingMetricsUpdated,
    ReplayPrepared,
    StreamStarted,
    WorkerError,
    WorkerEvent,
    WorkerStateChanged,
)
from quickreplay.recording.models import RecordingSession, WorkerErrorCode, WorkerState
from quickreplay.replay.asset_builder import ReplayAssetBuilder
from quickreplay.replay.models import ReplaySnapshot
from quickreplay.worker.errors import WorkerPipelineError, map_worker_error
from quickreplay.worker.inputs import InputSourceHandle, discover_inputs, open_input_source
from quickreplay.worker.pipeline import CLOCK, RecordingPipeline
from quickreplay.worker.settings import RecorderWorkerSettings


class CommandSource(Protocol):
    """A blocking command source (``multiprocessing.Queue`` or ``queue.Queue``)."""

    def get(self, block: bool = True, timeout: float | None = None) -> WorkerCommand: ...


_POLL_SECONDS = 0.05


class RecorderWorkerRuntime:
    """Command loop for the recorder worker."""

    def __init__(
        self,
        settings: RecorderWorkerSettings,
        *,
        command_queue: CommandSource,
        emit: Callable[[WorkerEvent], None],
        input_factory: Callable[[InputConfig], InputSourceHandle] = open_input_source,
        discovery: Callable[[], tuple[InputDescriptor, ...]] = discover_inputs,
        builder_factory: Callable[[], ReplayAssetBuilder] = ReplayAssetBuilder,
        clock: Callable[[], int] = CLOCK,
    ) -> None:
        self._settings = settings
        self._command_queue = command_queue
        self._emit = emit
        self._input_factory = input_factory
        self._discovery = discovery
        self._builder_factory = builder_factory
        self._clock = clock

        self._state: WorkerState | None = None
        self._pipeline: RecordingPipeline | None = None
        self._config: InputConfig | None = None
        self._running = True
        self._last_metrics_ns = 0

    @property
    def state(self) -> WorkerState | None:
        return self._state

    # -- main loop ---------------------------------------------------------
    def run(self) -> None:
        """Process commands until ``Shutdown`` is received."""
        self._set_state(WorkerState.IDLE)
        while self._running:
            try:
                command = self._command_queue.get(timeout=_POLL_SECONDS)
            except queue.Empty:
                command = None
            if command is not None:
                self._dispatch(command)
            if self._running:
                self._tick()

    def _dispatch(self, command: WorkerCommand) -> None:
        match command:
            case StartRecording():
                self._on_start(command)
            case PrepareReplay():
                self._on_prepare(command)
            case ResumeRecording():
                self._on_resume(command)
            case ChangeInput():
                self._on_change(command)
            case DiscoverInputs():
                self._on_discover(command)
            case Shutdown():
                self._on_shutdown()
            case _:  # pragma: no cover - future commands
                self._emit(
                    WorkerError(
                        WorkerErrorCode.INTERNAL_ERROR, f"unknown command {command!r}", None
                    )
                )

    def _tick(self) -> None:
        pipeline = self._pipeline
        if pipeline is not None and self._state in (WorkerState.RECORDING, WorkerState.STARTING):
            fatal = pipeline.poll_fatal()
            if fatal is not None:
                self._fail(fatal, None)
                return
        if self._state == WorkerState.RECORDING and pipeline is not None:
            now = self._clock()
            if now - self._last_metrics_ns >= self._settings.metrics_interval_ns:
                self._last_metrics_ns = now
                self._emit(RecordingMetricsUpdated(metrics=pipeline.metrics()))

    # -- command handlers --------------------------------------------------
    def _on_start(self, command: StartRecording) -> None:
        if self._state != WorkerState.IDLE:
            self._reject(None, "StartRecording is only valid while idle")
            return
        self._set_state(WorkerState.STARTING)
        self._begin_session(command.input_config, None)

    def _on_prepare(self, command: PrepareReplay) -> None:
        pipeline = self._pipeline
        if self._state != WorkerState.RECORDING or pipeline is None:
            self._reject(command.request_id, "PrepareReplay requires an active recording")
            return
        self._set_state(WorkerState.FREEZING)
        replay_directory = self._settings.replay_root / str(command.request_id)
        try:
            pipeline.stop()
            ring = pipeline.take_ring()
            info = pipeline.stream_info
            if ring is None or info is None:
                raise WorkerPipelineError("the recording pipeline is not ready to freeze")
            builder = self._builder_factory()
            with ring.snapshot() as lease:
                snapshot = ReplaySnapshot(segments=lease.segments, stream_info=info)
                asset = builder.build(snapshot, replay_directory)
            ring.clear()
            self._remove_session_directory(pipeline.session)
            self._pipeline = None
        except BaseException as exc:  # noqa: BLE001 - reported as a worker error
            self._remove_path_quietly(replay_directory)
            self._fail(exc, command.request_id)
            return
        self._set_state(WorkerState.FROZEN)
        self._emit(ReplayPrepared(request_id=command.request_id, asset=asset))

    def _on_resume(self, command: ResumeRecording) -> None:
        if self._state != WorkerState.FROZEN:
            self._reject(command.request_id, "ResumeRecording requires a frozen worker")
            return
        self._set_state(WorkerState.STARTING)
        try:
            self._purge_replay_root()
        except BaseException as exc:  # noqa: BLE001 - reported as a worker error
            self._fail(exc, command.request_id)
            return
        if self._config is None:
            self._fail(
                WorkerPipelineError("no input configuration available to resume"),
                command.request_id,
            )
            return
        self._begin_session(self._config, command.request_id)

    def _on_change(self, command: ChangeInput) -> None:
        pipeline = self._pipeline
        if self._state != WorkerState.RECORDING or pipeline is None:
            self._reject(command.request_id, "ChangeInput requires an active recording")
            return
        self._set_state(WorkerState.STOPPING)
        try:
            pipeline.stop()
            ring = pipeline.take_ring()
            if ring is not None:
                ring.clear()
            self._remove_session_directory(pipeline.session)
        except BaseException as exc:  # noqa: BLE001 - reported as a worker error
            self._fail(exc, command.request_id)
            return
        self._pipeline = None
        self._config = command.input_config
        self._set_state(WorkerState.STARTING)
        self._begin_session(command.input_config, command.request_id)

    def _on_discover(self, command: DiscoverInputs) -> None:
        try:
            inputs = self._discovery()
        except BaseException as exc:  # noqa: BLE001 - discovery failure is non-fatal
            self._emit(WorkerError(map_worker_error(exc), str(exc), command.request_id))
            return
        self._emit(InputsDiscovered(request_id=command.request_id, inputs=tuple(inputs)))

    def _on_shutdown(self) -> None:
        self._set_state(WorkerState.SHUTTING_DOWN)
        self._cleanup_all()
        self._running = False

    # -- session lifecycle -------------------------------------------------
    def _begin_session(self, config: InputConfig, request_id: UUID | None) -> None:
        pipeline = RecordingPipeline(
            self._settings, input_factory=self._input_factory, clock=self._clock
        )
        try:
            info = pipeline.start(config)
        except BaseException as exc:  # noqa: BLE001 - reported as a worker error
            pipeline.abort()
            self._fail(exc, request_id)
            return
        self._pipeline = pipeline
        self._config = config
        self._last_metrics_ns = self._clock()
        self._set_state(WorkerState.RECORDING)
        self._emit(StreamStarted(stream_info=info, request_id=request_id))

    # -- helpers -----------------------------------------------------------
    def _set_state(self, state: WorkerState) -> None:
        if self._state == state:
            return
        self._state = state
        self._emit(WorkerStateChanged(state=state))

    def _reject(self, request_id: UUID | None, message: str) -> None:
        self._emit(WorkerError(WorkerErrorCode.INTERNAL_ERROR, message, request_id))

    def _fail(self, exc: BaseException, request_id: UUID | None) -> None:
        code = map_worker_error(exc)
        if self._pipeline is not None:
            try:
                self._pipeline.abort()
            except Exception:  # noqa: BLE001 - best effort
                pass
            self._pipeline = None
        self._emit(WorkerError(code=code, message=str(exc), request_id=request_id))
        if self._state != WorkerState.SHUTTING_DOWN:
            self._set_state(WorkerState.ERROR)

    def _cleanup_all(self) -> None:
        pipeline = self._pipeline
        if pipeline is not None:
            try:
                pipeline.stop()
            except Exception:  # noqa: BLE001 - best effort
                pass
            try:
                ring = pipeline.take_ring()
                if ring is not None:
                    ring.clear()
            except Exception:  # noqa: BLE001 - best effort
                pass
            try:
                self._remove_session_directory(pipeline.session)
            except Exception:  # noqa: BLE001 - best effort
                pass
            self._pipeline = None
        try:
            self._purge_replay_root()
        except Exception:  # noqa: BLE001 - best effort
            pass

    def _remove_session_directory(self, session: RecordingSession | None) -> None:
        if session is None:
            return
        if session.directory.exists():
            shutil.rmtree(session.directory)

    def _purge_replay_root(self) -> None:
        root = self._settings.replay_root
        if not root.exists():
            return
        for entry in root.iterdir():
            if entry.is_dir():
                shutil.rmtree(entry)
            else:
                entry.unlink()

    def _remove_path_quietly(self, path: Path) -> None:
        shutil.rmtree(path, ignore_errors=True)
