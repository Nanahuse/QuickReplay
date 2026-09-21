"""Fake mpv process and IPC transport for controller tests."""

import json
import queue
from collections.abc import Callable, Sequence
from typing import Any

from quickreplay.replay.controller import ReplayController, ReplayControllerSettings


class FakeProcess:
    """A scripted mpv process."""

    def __init__(
        self,
        *,
        running: bool = True,
        exit_on_quit: bool = True,
        wait_results: Sequence[int | None] | None = None,
        terminate_works: bool = True,
        kill_works: bool = True,
    ) -> None:
        self._running = running
        self._returncode: int | None = 0 if not running else None
        self._wait_results = list(wait_results or [])
        self.exit_on_quit = exit_on_quit
        self.terminate_works = terminate_works
        self.kill_works = kill_works
        self.terminate_calls = 0
        self.kill_calls = 0
        self.wait_calls = 0

    def poll(self) -> int | None:
        return None if self._running else self._returncode

    def wait(self, timeout: float | None = None) -> int | None:
        self.wait_calls += 1
        if not self._running:
            return self._returncode
        if self._wait_results:
            result = self._wait_results.pop(0)
            if result is None:
                return None
            self.mark_exited(result)
            return result
        return None

    def terminate(self) -> None:
        self.terminate_calls += 1
        if self.terminate_works:
            self.mark_exited(-15)

    def kill(self) -> None:
        self.kill_calls += 1
        if self.kill_works:
            self.mark_exited(-9)

    def mark_exited(self, code: int = 0) -> None:
        self._running = False
        self._returncode = code

    @property
    def returncode(self) -> int | None:
        return self._returncode


Handler = Callable[[list[Any], int], dict[str, Any] | None]


class FakeTransport:
    """A scripted, line-oriented mpv IPC transport."""

    def __init__(
        self,
        *,
        process: FakeProcess | None = None,
        handler: Handler | None = None,
        connect_error: BaseException | None = None,
    ) -> None:
        self._lines: queue.Queue[bytes | None] = queue.Queue()
        self._process = process
        self._handler: Handler = handler or (lambda _command, _rid: {"error": "success"})
        self._connect_error = connect_error
        self.sent: list[dict[str, Any]] = []
        self.raw: list[bytes] = []
        self.connected = False
        self.closed = False

    def connect(self, endpoint: str) -> None:
        if self._connect_error is not None:
            raise self._connect_error
        self.connected = True

    def write_line(self, data: bytes) -> None:
        self.raw.append(data)
        message = json.loads(data.decode("utf-8"))
        self.sent.append(message)
        request_id = message.get("request_id")
        command = message.get("command", [])
        response = self._handler(command, request_id)
        if response is not None:
            payload = dict(response)
            payload.setdefault("request_id", request_id)
            self.inject_line((json.dumps(payload) + "\n").encode("utf-8"))
        if command and command[0] == "quit" and self._process is not None:
            if self._process.exit_on_quit:
                self._process.mark_exited(0)

    def inject_line(self, line: bytes) -> None:
        self._lines.put(line)

    def inject_json(self, message: dict[str, Any]) -> None:
        self.inject_line((json.dumps(message) + "\n").encode("utf-8"))

    def read_line(self, timeout: float) -> bytes | None:
        try:
            return self._lines.get(timeout=timeout)
        except queue.Empty:
            return None

    def close(self) -> None:
        self.closed = True

    def commands(self) -> list[list[Any]]:
        return [message.get("command", []) for message in self.sent]


class FakeMpvState:
    """Mutable mpv property state used by the default handler."""

    def __init__(self) -> None:
        self.time_pos: float | None = 0.0
        self.pause = True
        self.duration: float | None = 2.0
        self.pause_changes: list[bool] = []

    def handler(self, command: list[Any], request_id: int) -> dict[str, Any] | None:
        if command and command[0] == "get_property":
            name = command[1] if len(command) > 1 else ""
            if name == "duration":
                return {"error": "success", "data": self.duration}
            if name == "time-pos":
                return {"error": "success", "data": self.time_pos}
            if name == "pause":
                return {"error": "success", "data": self.pause}
        elif command and command[0] == "set_property":
            if len(command) > 2 and command[1] == "pause":
                self.pause = bool(command[2])
                self.pause_changes.append(self.pause)
        return {"error": "success"}


class FakeMpv:
    """A fake mpv instance plus a controller wired to it."""

    def __init__(
        self,
        *,
        running: bool = True,
        exit_on_quit: bool = True,
        wait_results: Sequence[int | None] | None = None,
        terminate_works: bool = True,
        kill_works: bool = True,
        handler: Handler | None = None,
        connect_error: BaseException | None = None,
        startup_timeout_seconds: float = 1.0,
        command_timeout_seconds: float = 1.0,
        shutdown_timeout_seconds: float = 0.5,
        mpv_executable: str = "mpv",
    ) -> None:
        self.state = FakeMpvState()
        self.process = FakeProcess(
            running=running,
            exit_on_quit=exit_on_quit,
            wait_results=wait_results,
            terminate_works=terminate_works,
            kill_works=kill_works,
        )
        self.transport = FakeTransport(
            process=self.process,
            handler=handler or self.state.handler,
            connect_error=connect_error,
        )
        self.arguments: list[str] | None = None
        self._settings = ReplayControllerSettings(
            mpv_executable=mpv_executable,
            startup_timeout_seconds=startup_timeout_seconds,
            command_timeout_seconds=command_timeout_seconds,
            shutdown_timeout_seconds=shutdown_timeout_seconds,
            connect_retry_interval_seconds=0.0,
        )

    def process_factory(self, arguments: Sequence[str]) -> FakeProcess:
        self.arguments = list(arguments)
        return self.process

    def transport_factory(self) -> FakeTransport:
        return self.transport

    def controller(self, **overrides: Any) -> ReplayController:
        settings = self._settings
        if overrides:
            settings = ReplayControllerSettings(
                mpv_executable=overrides.get("mpv_executable", settings.mpv_executable),
                startup_timeout_seconds=overrides.get(
                    "startup_timeout_seconds", settings.startup_timeout_seconds
                ),
                command_timeout_seconds=overrides.get(
                    "command_timeout_seconds", settings.command_timeout_seconds
                ),
                shutdown_timeout_seconds=overrides.get(
                    "shutdown_timeout_seconds", settings.shutdown_timeout_seconds
                ),
                connect_retry_interval_seconds=0.0,
            )
        return ReplayController(
            settings,
            process_factory=self.process_factory,
            transport_factory=self.transport_factory,
            sleep=lambda _seconds: None,
        )
