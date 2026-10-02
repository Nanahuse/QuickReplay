"""Headless application controller.

Coordinates the recorder worker process and the mpv replay controller.  It owns
both components, translates the worker protocol into UI-independent application
events, correlates asynchronous responses by request id and drives the
recording/replay/resume lifecycle.  It never captures frames, encodes, builds
replay assets or talks to mpv directly.
"""

import functools
import time
from collections.abc import Callable
from typing import Protocol, TypeVar
from uuid import UUID, uuid4

from quickreplay.app.state import ApplicationState
from quickreplay.application.errors import (
    ApplicationControllerError,
    InvalidApplicationStateError,
    WorkerStartupError,
)
from quickreplay.application.events import (
    ApplicationError,
    ApplicationEvent,
    ApplicationStateChanged,
    InputsChanged,
    RecordingMetricsChanged,
    RecordingStarted,
    ReplayStarted,
)
from quickreplay.application.models import (
    ApplicationControllerSettings,
    ApplicationSnapshot,
)
from quickreplay.input.models import InputConfig
from quickreplay.recording.commands import (
    ChangeInput,
    DiscoverInputs,
    PrepareReplay,
    ResumeRecording,
    Shutdown,
    StartRecording,
    StopSession,
    WorkerCommand,
)
from quickreplay.recording.events import (
    InputsDiscovered,
    RecordingMetricsUpdated,
    ReplayPrepared,
    SessionStopped,
    StreamStarted,
    WorkerError,
    WorkerEvent,
    WorkerStateChanged,
)
from quickreplay.recording.models import RecordingMetrics, WorkerErrorCode, WorkerState
from quickreplay.replay.controller import ReplayController
from quickreplay.replay.errors import MpvProcessExitedError
from quickreplay.replay.models import ReplayAsset, SetPoint
from quickreplay.worker.process import RecorderWorkerProcess
from quickreplay.worker.settings import RecorderWorkerSettings

_START = "start"
_CHANGE = "change"

_T = TypeVar("_T")


class WorkerHandle(Protocol):
    """The worker operations the application controller needs."""

    def start(self) -> None: ...

    def send(self, command: WorkerCommand) -> None: ...

    def get_event(self, timeout: float | None = None) -> WorkerEvent | None: ...

    def is_alive(self) -> bool: ...

    @property
    def exitcode(self) -> int | None: ...

    def join(self, timeout: float | None = None) -> None: ...

    def terminate(self) -> None: ...

    def close(self) -> None: ...


class ReplayControllerLike(Protocol):
    """The replay playback operations the application controller delegates."""

    def open(self, asset: ReplayAsset) -> None: ...

    def close(self) -> None: ...

    @property
    def asset(self) -> ReplayAsset | None: ...

    @property
    def is_open(self) -> bool: ...

    def check_alive(self) -> None: ...

    def play(self) -> None: ...

    def pause(self) -> None: ...

    def is_paused(self) -> bool: ...

    def step_forward(self) -> None: ...

    def step_backward(self) -> None: ...

    def seek_frames(self, frames: int) -> None: ...

    def seek_absolute_ns(self, position_ns: int) -> None: ...

    def position_ns(self) -> int: ...

    def set_point(self) -> SetPoint: ...

    def time_difference_ns(self, point: SetPoint) -> int: ...

    def frame_difference(self, point: SetPoint) -> int: ...


def _default_worker_factory(settings: ApplicationControllerSettings) -> WorkerHandle:
    worker_settings: RecorderWorkerSettings | None = settings.worker
    if worker_settings is None:
        raise ApplicationControllerError(
            "RecorderWorkerSettings are required to build the recorder worker"
        )
    return RecorderWorkerProcess(worker_settings)


def _default_replay_factory(settings: ApplicationControllerSettings) -> ReplayControllerLike:
    return ReplayController(settings.replay)


class ApplicationController:
    """Coordinate recording and replay for a headless QuickReplay core."""

    def __init__(
        self,
        settings: ApplicationControllerSettings | None = None,
        *,
        worker_factory: Callable[[], WorkerHandle] | None = None,
        replay_controller_factory: Callable[[], ReplayControllerLike] | None = None,
        request_id_factory: Callable[[], UUID] = uuid4,
    ) -> None:
        self._settings = settings or ApplicationControllerSettings()
        self._worker_factory = worker_factory or functools.partial(
            _default_worker_factory, self._settings
        )
        self._replay_factory = replay_controller_factory or functools.partial(
            _default_replay_factory, self._settings
        )
        self._request_id_factory = request_id_factory

        self._state = ApplicationState.STARTING
        self._worker: WorkerHandle | None = None
        self._replay: ReplayControllerLike | None = None

        self._stream_info = None
        self._metrics: RecordingMetrics | None = None
        self._replay_asset: ReplayAsset | None = None
        self._error_message: str | None = None

        self._pending_kind: str | None = None
        self._pending_start_request_id: UUID | None = None
        self._pending_stream_request_id: UUID | None = None
        self._pending_replay_request_id: UUID | None = None
        self._pending_resume_request_id: UUID | None = None
        self._pending_stop_request_id: UUID | None = None
        self._pending_discovery_ids: set[UUID] = set()

        self._events: list[ApplicationEvent] = []
        self._started = False

    # -- queries -----------------------------------------------------------
    @property
    def state(self) -> ApplicationState:
        return self._state

    @property
    def stream_info(self):
        return self._stream_info

    @property
    def replay_asset(self) -> ReplayAsset | None:
        return self._replay_asset

    def snapshot(self) -> ApplicationSnapshot:
        """A read-only view of the current application state."""
        return ApplicationSnapshot(
            state=self._state,
            stream_info=self._stream_info,
            metrics=self._metrics,
            replay_asset=self._replay_asset,
            error_message=self._error_message,
        )

    # -- lifecycle ---------------------------------------------------------
    def start(self) -> None:
        """Start the recorder worker and wait until it is idle."""
        if self._worker is not None or self._started:
            raise InvalidApplicationStateError("the application has already been started")
        self._started = True
        self._set_state(ApplicationState.STARTING)
        worker = self._worker_factory()
        self._worker = worker
        try:
            worker.start()
            self._wait_for_worker_idle()
        except BaseException as exc:
            self._fail(str(exc), source="worker")
            raise WorkerStartupError(str(exc)) from exc
        self._set_state(ApplicationState.IDLE)

    def start_recording(self, input_config: InputConfig) -> None:
        """Start a fresh recording session from *input_config*."""
        self._require_state(ApplicationState.IDLE, "start_recording")
        request_id = self._request_id_factory()
        self._stream_info = None
        self._metrics = None
        self._replay_asset = None
        self._error_message = None
        self._pending_replay_request_id = None
        self._pending_resume_request_id = None
        self._pending_start_request_id = request_id
        self._pending_kind = _START
        self._pending_stream_request_id = request_id
        self._set_state(ApplicationState.STARTING)
        self._send(StartRecording(request_id=request_id, input_config=input_config))

    def request_replay(self) -> UUID:
        """Freeze the buffer and build a replay asset."""
        self._require_state(ApplicationState.RECORDING, "request_replay")
        if self._pending_replay_request_id is not None:
            raise InvalidApplicationStateError("a replay request is already pending")
        request_id = self._request_id_factory()
        self._pending_replay_request_id = request_id
        self._metrics = None
        self._set_state(ApplicationState.PREPARING_REPLAY)
        self._send(PrepareReplay(request_id))
        return request_id

    def resume_recording(self) -> UUID:
        """Close the replay and resume recording."""
        self._require_state(ApplicationState.REPLAY, "resume_recording")
        if self._pending_resume_request_id is not None:
            raise InvalidApplicationStateError("a resume request is already pending")
        self._close_replay()
        return self._begin_resume()

    def stop_session(self) -> UUID:
        """Discard the current session and return to idle without stopping the worker."""
        self._require_state_any(
            (ApplicationState.RECORDING, ApplicationState.REPLAY), "stop_session"
        )
        if self._pending_stop_request_id is not None:
            raise InvalidApplicationStateError("a stop session request is already pending")
        request_id = self._request_id_factory()
        self._pending_stop_request_id = request_id
        self._set_state(ApplicationState.STOPPING)
        self._close_replay()
        self._send(StopSession(request_id))
        return request_id

    def change_input(self, input_config: InputConfig) -> UUID:
        """Switch the active input while recording."""
        self._require_state(ApplicationState.RECORDING, "change_input")
        request_id = self._request_id_factory()
        self._pending_kind = _CHANGE
        self._pending_stream_request_id = request_id
        self._set_state(ApplicationState.STARTING)
        self._send(ChangeInput(request_id, input_config))
        return request_id

    def discover_inputs(self) -> UUID:
        """Request the list of available inputs (allowed while recording/replaying)."""
        if self._state not in (
            ApplicationState.IDLE,
            ApplicationState.RECORDING,
            ApplicationState.REPLAY,
        ):
            raise InvalidApplicationStateError(
                f"discover_inputs is not allowed in state {self._state}"
            )
        request_id = self._request_id_factory()
        self._pending_discovery_ids.add(request_id)
        self._send(DiscoverInputs(request_id))
        return request_id

    def shutdown(self) -> None:
        """Stop replay and the worker, then release the IPC queues."""
        if self._state == ApplicationState.SHUTTING_DOWN:
            return
        self._set_state(ApplicationState.SHUTTING_DOWN)
        self._close_replay()
        worker = self._worker
        if worker is None:
            return
        try:
            worker.send(Shutdown())
        except Exception:  # noqa: BLE001 - best effort
            pass
        timeout = self._settings.worker_shutdown_timeout_seconds
        worker.join(timeout=timeout)
        if worker.is_alive():
            worker.terminate()
            worker.join(timeout=timeout)
        if not worker.is_alive():
            try:
                worker.close()
            except Exception:  # noqa: BLE001 - best effort
                pass
        self._worker = None

    # -- event loop --------------------------------------------------------
    def poll(self, timeout: float = 0.0) -> tuple[ApplicationEvent, ...]:
        """Process worker events and return the application events produced."""
        self._drain_worker_events(timeout)
        self._check_worker_liveness()
        self._check_replay_liveness()
        events = tuple(self._events)
        self._events.clear()
        return events

    # -- replay delegation -------------------------------------------------
    def play(self) -> None:
        self._call_replay(lambda replay: replay.play())

    def pause(self) -> None:
        self._call_replay(lambda replay: replay.pause())

    def is_paused(self) -> bool:
        return self._call_replay(lambda replay: replay.is_paused())

    def step_forward(self) -> None:
        self._call_replay(lambda replay: replay.step_forward())

    def step_backward(self) -> None:
        self._call_replay(lambda replay: replay.step_backward())

    def seek_frames(self, frames: int) -> None:
        self._call_replay(lambda replay: replay.seek_frames(frames))

    def seek_absolute_ns(self, position_ns: int) -> None:
        self._call_replay(lambda replay: replay.seek_absolute_ns(position_ns))

    def replay_position_ns(self) -> int:
        return self._call_replay(lambda replay: replay.position_ns())

    def set_point(self) -> SetPoint:
        return self._call_replay(lambda replay: replay.set_point())

    def time_difference_ns(self, point: SetPoint) -> int:
        return self._call_replay(lambda replay: replay.time_difference_ns(point))

    def frame_difference(self, point: SetPoint) -> int:
        return self._call_replay(lambda replay: replay.frame_difference(point))

    # -- worker event handling ---------------------------------------------
    def _drain_worker_events(self, timeout: float) -> None:
        worker = self._worker
        if worker is None:
            return
        first = worker.get_event(timeout=timeout)
        if first is not None:
            self._handle_worker_event(first)
        while True:
            event = worker.get_event(timeout=0)
            if event is None:
                return
            self._handle_worker_event(event)

    def _handle_worker_event(self, event: WorkerEvent) -> None:
        match event:
            case WorkerStateChanged():
                self._handle_worker_state(event.state)
            case StreamStarted():
                self._handle_stream_started(event)
            case ReplayPrepared():
                self._handle_replay_prepared(event)
            case SessionStopped():
                self._handle_session_stopped(event)
            case RecordingMetricsUpdated():
                self._handle_metrics(event.metrics)
            case InputsDiscovered():
                self._handle_inputs_discovered(event)
            case WorkerError():
                self._handle_worker_error(event)

    def _handle_worker_state(self, state: WorkerState) -> None:
        if state == WorkerState.ERROR and self._state not in (
            ApplicationState.ERROR,
            ApplicationState.SHUTTING_DOWN,
        ):
            self._fail("the recorder worker entered an error state", source="worker")

    def _handle_stream_started(self, event: StreamStarted) -> None:
        if self._state == ApplicationState.STARTING:
            if self._pending_kind == _START and event.request_id == self._pending_start_request_id:
                self._accept_stream(event)
                return
            if (
                self._pending_kind == _CHANGE
                and event.request_id == self._pending_stream_request_id
            ):
                self._accept_stream(event)
                return
            return
        if (
            self._state == ApplicationState.RESUMING
            and event.request_id == self._pending_resume_request_id
        ):
            self._pending_resume_request_id = None
            self._metrics = None
            self._accept_stream(event)

    def _accept_stream(self, event: StreamStarted) -> None:
        self._stream_info = event.stream_info
        self._pending_kind = None
        self._pending_start_request_id = None
        self._pending_stream_request_id = None
        self._set_state(ApplicationState.RECORDING)
        self._emit(RecordingStarted(stream_info=event.stream_info))

    def _handle_replay_prepared(self, event: ReplayPrepared) -> None:
        if self._state != ApplicationState.PREPARING_REPLAY:
            return
        if event.request_id != self._pending_replay_request_id:
            return
        replay = self._replay_factory()
        try:
            replay.open(event.asset)
        except BaseException as exc:  # noqa: BLE001 - reported as an application error
            try:
                replay.close()
            except Exception:  # noqa: BLE001 - best effort
                pass
            self._fail(f"could not open the replay: {exc}", source="replay")
            return
        self._replay = replay
        self._replay_asset = event.asset
        self._pending_replay_request_id = None
        self._metrics = None
        self._set_state(ApplicationState.REPLAY)
        self._emit(ReplayStarted(asset=event.asset))

    def _handle_session_stopped(self, event: SessionStopped) -> None:
        if event.request_id != self._pending_stop_request_id:
            return
        self._pending_stop_request_id = None
        self._stream_info = None
        self._metrics = None
        self._replay_asset = None
        self._pending_kind = None
        self._pending_start_request_id = None
        self._pending_stream_request_id = None
        self._pending_replay_request_id = None
        self._pending_resume_request_id = None
        self._error_message = None
        self._set_state(ApplicationState.IDLE)

    def _handle_metrics(self, metrics: RecordingMetrics) -> None:
        if self._state != ApplicationState.RECORDING:
            return
        self._metrics = metrics
        self._emit(RecordingMetricsChanged(metrics=metrics))

    def _handle_inputs_discovered(self, event: InputsDiscovered) -> None:
        if event.request_id not in self._pending_discovery_ids:
            return
        self._pending_discovery_ids.discard(event.request_id)
        self._emit(InputsChanged(request_id=event.request_id, inputs=event.inputs))

    def _handle_worker_error(self, event: WorkerError) -> None:
        request_id = event.request_id
        if request_id is not None and request_id in self._pending_discovery_ids:
            self._pending_discovery_ids.discard(request_id)
            self._emit(
                ApplicationError(
                    message=event.message,
                    source="worker",
                    code=event.code,
                    request_id=request_id,
                )
            )
            return
        if request_id is not None:
            if self._state == ApplicationState.STARTING:
                expected_id = (
                    self._pending_start_request_id
                    if self._pending_kind == _START
                    else self._pending_stream_request_id
                )
                if request_id != expected_id:
                    return
            elif self._state == ApplicationState.RESUMING:
                if request_id != self._pending_resume_request_id:
                    return
            elif self._state == ApplicationState.PREPARING_REPLAY:
                if request_id != self._pending_replay_request_id:
                    return
            elif self._state == ApplicationState.STOPPING:
                if request_id != self._pending_stop_request_id:
                    return
            else:
                return
        self._fail(event.message, source="worker", code=event.code, request_id=request_id)

    # -- replay liveness ---------------------------------------------------
    def _call_replay(self, action: Callable[[ReplayControllerLike], _T]) -> _T:
        replay = self._require_replay()
        try:
            return action(replay)
        except MpvProcessExitedError:
            self._handle_replay_exit()
            raise

    def _check_replay_liveness(self) -> None:
        if self._state != ApplicationState.REPLAY or self._replay is None:
            return
        try:
            self._replay.check_alive()
        except MpvProcessExitedError:
            self._handle_replay_exit()

    def _handle_replay_exit(self) -> None:
        if self._state != ApplicationState.REPLAY:
            return
        self._close_replay()
        self._begin_resume()

    def _begin_resume(self) -> UUID:
        request_id = self._request_id_factory()
        self._pending_resume_request_id = request_id
        self._set_state(ApplicationState.RESUMING)
        self._send(ResumeRecording(request_id))
        return request_id

    def _close_replay(self) -> None:
        replay = self._replay
        self._replay = None
        self._replay_asset = None
        if replay is not None:
            try:
                replay.close()
            except Exception:  # noqa: BLE001 - best effort
                pass

    # -- worker liveness ---------------------------------------------------
    def _check_worker_liveness(self) -> None:
        worker = self._worker
        if worker is None:
            return
        if self._state in (ApplicationState.ERROR, ApplicationState.SHUTTING_DOWN):
            return
        if not worker.is_alive():
            self._fail(f"the recorder worker exited with code {worker.exitcode}", source="worker")

    # -- helpers -----------------------------------------------------------
    def _wait_for_worker_idle(self) -> None:
        worker = self._worker
        if worker is None:  # pragma: no cover - defensive
            raise WorkerStartupError("the recorder worker is not available")
        deadline = time.monotonic() + self._settings.worker_start_timeout_seconds
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise WorkerStartupError("timed out waiting for the worker to start")
            event = worker.get_event(timeout=remaining)
            if event is None:
                if not worker.is_alive():
                    raise WorkerStartupError(
                        f"the recorder worker exited with code {worker.exitcode}"
                    )
                continue
            if isinstance(event, WorkerStateChanged) and event.state == WorkerState.IDLE:
                return
            if isinstance(event, WorkerError):
                raise WorkerStartupError(event.message)

    def _require_state(self, expected: ApplicationState, operation: str) -> None:
        if self._state != expected:
            raise InvalidApplicationStateError(f"{operation} is not allowed in state {self._state}")

    def _require_state_any(self, expected: tuple[ApplicationState, ...], operation: str) -> None:
        if self._state not in expected:
            raise InvalidApplicationStateError(f"{operation} is not allowed in state {self._state}")

    def _require_replay(self) -> ReplayControllerLike:
        if self._state != ApplicationState.REPLAY or self._replay is None:
            raise InvalidApplicationStateError("replay is not active")
        try:
            self._replay.check_alive()
        except MpvProcessExitedError:
            self._handle_replay_exit()
            raise
        return self._replay

    def _send(self, command: WorkerCommand) -> None:
        worker = self._worker
        if worker is None:
            raise ApplicationControllerError("the recorder worker is not running")
        worker.send(command)

    def _set_state(self, state: ApplicationState) -> None:
        if self._state == state:
            return
        self._state = state
        self._emit(ApplicationStateChanged(state=state))

    def _fail(
        self,
        message: str,
        *,
        source: str,
        code: WorkerErrorCode | None = None,
        request_id: UUID | None = None,
    ) -> None:
        if self._state in (ApplicationState.ERROR, ApplicationState.SHUTTING_DOWN):
            return
        self._error_message = message
        self._emit(
            ApplicationError(message=message, source=source, code=code, request_id=request_id)
        )
        self._set_state(ApplicationState.ERROR)

    def _emit(self, event: ApplicationEvent) -> None:
        self._events.append(event)
