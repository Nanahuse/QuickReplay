"""Fakes for headless UI tests (no Flet, no display)."""

import threading
import time
from uuid import UUID, uuid4

from quickreplay.app.state import ApplicationState
from quickreplay.application.events import ApplicationEvent
from quickreplay.application.models import ApplicationSnapshot
from quickreplay.input.models import InputConfig


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
