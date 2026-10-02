"""Fake worker and replay controller for application controller tests."""

import queue
from fractions import Fraction
from typing import Any
from uuid import uuid4

from quickreplay.recording.commands import WorkerCommand
from quickreplay.recording.events import WorkerEvent, WorkerStateChanged
from quickreplay.recording.models import WorkerState
from quickreplay.replay.errors import MpvProcessExitedError
from quickreplay.replay.models import ReplayAsset, SetPoint, frame_difference


class FakeWorker:
    """A scripted :class:`WorkerHandle`."""

    def __init__(self, *, auto_idle: bool = True, exit_on_shutdown: bool = True) -> None:
        self.commands: list[WorkerCommand] = []
        self.events: queue.Queue[WorkerEvent] = queue.Queue()
        self.order: list[tuple[str, str | None]] = []
        self.started = False
        self.alive = True
        self.exitcode_value: int | None = None
        self.auto_idle = auto_idle
        self.exit_on_shutdown = exit_on_shutdown
        self.join_calls = 0
        self.terminate_calls = 0
        self.closed = False

    def start(self) -> None:
        self.started = True
        if self.auto_idle:
            self.push(WorkerStateChanged(state=WorkerState.IDLE))

    def send(self, command: WorkerCommand) -> None:
        self.commands.append(command)
        self.order.append(("worker.send", type(command).__name__))

    def get_event(self, timeout: float | None = None) -> WorkerEvent | None:
        try:
            return self.events.get(timeout=timeout)
        except queue.Empty:
            return None

    def push(self, event: WorkerEvent) -> None:
        self.events.put(event)

    def is_alive(self) -> bool:
        return self.alive

    @property
    def exitcode(self) -> int | None:
        return self.exitcode_value

    def join(self, timeout: float | None = None) -> None:
        self.join_calls += 1
        if self.exit_on_shutdown:
            self.alive = False
            if self.exitcode_value is None:
                self.exitcode_value = 0

    def terminate(self) -> None:
        self.terminate_calls += 1
        self.alive = False
        self.exitcode_value = -9

    def close(self) -> None:
        self.closed = True

    def die(self, code: int = 1) -> None:
        self.alive = False
        self.exitcode_value = code

    def commands_of(self, command_type: type) -> list[Any]:
        return [command for command in self.commands if isinstance(command, command_type)]


class FakeReplayController:
    """A scripted :class:`ReplayControllerLike`."""

    def __init__(
        self,
        *,
        open_error: BaseException | None = None,
        dead: bool = False,
        order: list[tuple[str, str | None]] | None = None,
    ) -> None:
        self.open_error = open_error
        self.dead = dead
        self.order = order if order is not None else []
        self.calls: list[Any] = []
        self.asset: ReplayAsset | None = None
        self.is_open = False
        self.paused = True
        self.position = 0

    def open(self, asset: ReplayAsset) -> None:
        self.calls.append("open")
        if self.open_error is not None:
            raise self.open_error
        self.asset = asset
        self.is_open = True

    def close(self) -> None:
        self.calls.append("close")
        self.order.append(("replay.close", None))
        self.is_open = False

    def check_alive(self) -> None:
        if self.dead:
            raise MpvProcessExitedError("the mpv process has exited")

    def play(self) -> None:
        self.calls.append("play")
        self.paused = False

    def pause(self) -> None:
        self.calls.append("pause")
        self.paused = True

    def is_paused(self) -> bool:
        return self.paused

    def step_forward(self) -> None:
        self.calls.append("step_forward")

    def step_backward(self) -> None:
        self.calls.append("step_backward")

    def seek_frames(self, frames: int) -> None:
        self.calls.append(("seek_frames", frames))

    def seek_absolute_ns(self, position_ns: int) -> None:
        self.calls.append(("seek_absolute_ns", position_ns))

    def position_ns(self) -> int:
        return self.position

    def set_point(self) -> SetPoint:
        return SetPoint(position_ns=self.position)

    def time_difference_ns(self, point: SetPoint) -> int:
        return self.position - point.position_ns

    def frame_difference(self, point: SetPoint) -> int:
        fps = self.asset.fps if self.asset is not None else Fraction(60, 1)
        return frame_difference(self.position, point.position_ns, fps)


class FakeReplayFactory:
    """Creates :class:`FakeReplayController` instances and records them."""

    def __init__(
        self,
        *,
        open_error: BaseException | None = None,
        order: list[tuple[str, str | None]] | None = None,
    ) -> None:
        self.open_error = open_error
        self.order = order if order is not None else []
        self.controllers: list[FakeReplayController] = []

    def __call__(self) -> FakeReplayController:
        controller = FakeReplayController(open_error=self.open_error, order=self.order)
        self.controllers.append(controller)
        return controller


class SequenceRequestIds:
    """Deterministic request id factory, falling back to random UUIDs."""

    def __init__(self, *request_ids: Any) -> None:
        self._ids = list(request_ids)

    def __call__(self) -> Any:
        if self._ids:
            return self._ids.pop(0)
        return uuid4()
