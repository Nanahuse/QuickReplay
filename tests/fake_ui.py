"""Fakes for headless UI tests (no Flet, no display)."""

import threading
import time
from uuid import UUID, uuid4

from quickreplay.app.state import ApplicationState
from quickreplay.application.events import ApplicationEvent
from quickreplay.application.models import ApplicationSnapshot
from quickreplay.input.models import InputConfig
from quickreplay.replay.models import SetPoint


class FakeController:
    """Records calls, the calling thread and the maximum concurrency."""

    def __init__(self, *, fail_on: str | None = None, delay: float = 0.01) -> None:
        self.calls: list[str] = []
        self.threads: list[int] = []
        self.fail_on = fail_on
        self.delay = delay
        self.active = 0
        self.max_active = 0

    def _record(self, name: str):
        self.calls.append(name)
        self.threads.append(threading.get_ident())
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            time.sleep(self.delay)
            if self.fail_on == name:
                raise RuntimeError(f"{name} failed")
            return name
        finally:
            self.active -= 1

    def start(self) -> None:
        self._record("start")

    def start_recording(self, input_config: InputConfig) -> None:
        self._record("start_recording")

    def discover_inputs(self, *, camera_backend: str = "any") -> UUID:
        self._record("discover_inputs")
        return uuid4()

    def request_replay(self) -> UUID:
        self._record("request_replay")
        return uuid4()

    def resume_recording(self) -> UUID:
        self._record("resume_recording")
        return uuid4()

    def poll(self, timeout: float = 0.0) -> tuple[ApplicationEvent, ...]:
        self._record("poll")
        return ()

    def snapshot(self) -> ApplicationSnapshot:
        self._record("snapshot")
        return ApplicationSnapshot(state=ApplicationState.IDLE)

    def shutdown(self) -> None:
        self._record("shutdown")

    # -- replay delegate ---------------------------------------------------
    def play(self) -> None:
        self._record("play")

    def pause(self) -> None:
        self._record("pause")

    def is_paused(self) -> bool:
        self._record("is_paused")
        return True

    def step_forward(self) -> None:
        self._record("step_forward")

    def step_backward(self) -> None:
        self._record("step_backward")

    def seek_frames(self, frames: int) -> None:
        self._record("seek_frames")

    def seek_absolute_ns(self, position_ns: int) -> None:
        self._record("seek_absolute_ns")

    def replay_position_ns(self) -> int:
        self._record("replay_position_ns")
        return 0

    def set_point(self) -> SetPoint:
        self._record("set_point")
        return SetPoint(position_ns=0)

    def time_difference_ns(self, point: SetPoint) -> int:
        self._record("time_difference_ns")
        return 0

    def frame_difference(self, point: SetPoint) -> int:
        self._record("frame_difference")
        return 0


class FakeBridge:
    """A scripted :class:`~quickreplay.ui.bridge.ApplicationUiBridge`."""

    def __init__(self) -> None:
        self.started = False
        self.recording_configs: list[InputConfig] = []
        self.discovery_requests: list[str] = []
        self.replay_requests = 0
        self.resume_requests = 0
        self.events: list[ApplicationEvent] = []
        self.snapshot_value = ApplicationSnapshot(state=ApplicationState.IDLE)
        self.next_discovery_id = uuid4()
        self.shutdown_called = False
        self.closed = False

        # -- replay recording --
        self.play_calls = 0
        self.pause_calls = 0
        self.step_forward_calls = 0
        self.step_backward_calls = 0
        self.seek_frames_calls: list[int] = []
        self.seek_absolute_calls: list[int] = []
        self.set_point_calls = 0
        self.position_calls = 0
        self.is_paused_calls = 0
        self.time_difference_points: list[SetPoint] = []
        self.frame_difference_points: list[SetPoint] = []
        self.position_value = 0
        self.paused_value = True
        self.set_point_value = 0
        self.time_difference_value = 0
        self.frame_difference_value = 0
        self.position_error: BaseException | None = None

    async def start(self) -> None:
        self.started = True

    async def start_recording(self, input_config: InputConfig) -> None:
        self.recording_configs.append(input_config)

    async def discover_inputs(self, *, camera_backend: str = "any") -> UUID:
        self.discovery_requests.append(camera_backend)
        self.next_discovery_id = uuid4()
        return self.next_discovery_id

    async def request_replay(self) -> UUID:
        self.replay_requests += 1
        return uuid4()

    async def resume_recording(self) -> UUID:
        self.resume_requests += 1
        return uuid4()

    async def poll(self, timeout: float = 0.0) -> tuple[ApplicationEvent, ...]:
        events = tuple(self.events)
        self.events = []
        return events

    async def snapshot(self) -> ApplicationSnapshot:
        return self.snapshot_value

    async def shutdown(self) -> None:
        self.shutdown_called = True

    async def close(self) -> None:
        self.closed = True

    # -- replay delegate ---------------------------------------------------
    async def play(self) -> None:
        self.play_calls += 1
        self.paused_value = False

    async def pause(self) -> None:
        self.pause_calls += 1
        self.paused_value = True

    async def is_paused(self) -> bool:
        self.is_paused_calls += 1
        return self.paused_value

    async def step_forward(self) -> None:
        self.step_forward_calls += 1

    async def step_backward(self) -> None:
        self.step_backward_calls += 1

    async def seek_frames(self, frames: int) -> None:
        self.seek_frames_calls.append(frames)

    async def seek_absolute_ns(self, position_ns: int) -> None:
        self.seek_absolute_calls.append(position_ns)

    async def replay_position_ns(self) -> int:
        self.position_calls += 1
        if self.position_error is not None:
            raise self.position_error
        return self.position_value

    async def set_point(self) -> SetPoint:
        self.set_point_calls += 1
        return SetPoint(position_ns=self.set_point_value)

    async def time_difference_ns(self, point: SetPoint) -> int:
        self.time_difference_points.append(point)
        return self.time_difference_value

    async def frame_difference(self, point: SetPoint) -> int:
        self.frame_difference_points.append(point)
        return self.frame_difference_value
