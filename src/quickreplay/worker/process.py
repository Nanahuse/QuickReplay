"""Spawn-based wrapper around the recorder worker process.

The worker runs in its own process created with an explicit ``spawn`` context
so no ``fork`` semantics are relied on (Windows packaging).  The process target
is a module-level function; importing this module never starts a process.
"""

import multiprocessing
import queue
from multiprocessing.process import BaseProcess
from typing import Any

from quickreplay.recording.commands import WorkerCommand
from quickreplay.recording.events import WorkerEvent
from quickreplay.worker.runtime import RecorderWorkerRuntime
from quickreplay.worker.settings import RecorderWorkerSettings


def worker_process_main(
    command_queue: Any, event_queue: Any, settings: RecorderWorkerSettings
) -> None:
    """Entry point of the worker process (module level, picklable)."""
    runtime = RecorderWorkerRuntime(settings, command_queue=command_queue, emit=event_queue.put)
    runtime.run()


def spawn_context() -> Any:
    """The explicit spawn context used for the worker process."""
    return multiprocessing.get_context("spawn")


class RecorderWorkerProcess:
    """Main-process handle for one long-lived recorder worker."""

    def __init__(self, settings: RecorderWorkerSettings, *, context: Any | None = None) -> None:
        self._settings = settings
        self._context = context if context is not None else spawn_context()
        self._command_queue = self._context.Queue()
        self._event_queue = self._context.Queue()
        self._process: BaseProcess | None = None

    def start(self) -> None:
        """Start the worker process."""
        if self._process is not None:
            raise RuntimeError("the worker process has already been started")
        self._process = self._context.Process(
            target=worker_process_main,
            args=(self._command_queue, self._event_queue, self._settings),
            name="QuickReplayRecorderWorker",
        )
        self._process.start()

    def send(self, command: WorkerCommand) -> None:
        """Send a command to the worker."""
        self._command_queue.put(command)

    def get_event(self, timeout: float | None = None) -> WorkerEvent | None:
        """Return the next worker event, or ``None`` when the timeout elapses."""
        try:
            return self._event_queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def is_alive(self) -> bool:
        """Whether the worker process is still running."""
        return self._process is not None and self._process.is_alive()

    @property
    def exitcode(self) -> int | None:
        """The process exit code, or ``None`` while it is still running."""
        return None if self._process is None else self._process.exitcode

    def join(self, timeout: float | None = None) -> None:
        """Wait for the worker process to exit."""
        if self._process is not None:
            self._process.join(timeout)

    def terminate(self) -> None:
        """Forcefully terminate the worker process."""
        if self._process is not None and self._process.is_alive():
            self._process.terminate()

    def close(self) -> None:
        """Close the IPC queues.  Call after the process has exited."""
        self._command_queue.close()
        self._event_queue.close()
