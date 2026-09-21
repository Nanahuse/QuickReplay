"""Spawn process integration for the recorder worker."""

import pickle
from pathlib import Path

from quickreplay.recording.commands import Shutdown
from quickreplay.recording.events import WorkerStateChanged
from quickreplay.recording.models import WorkerState
from quickreplay.worker.process import (
    RecorderWorkerProcess,
    spawn_context,
    worker_process_main,
)
from quickreplay.worker.settings import RecorderWorkerSettings


def test_worker_process_main_is_a_module_level_function() -> None:
    restored = pickle.loads(pickle.dumps(worker_process_main))
    assert restored is worker_process_main


def test_spawn_context_is_spawn() -> None:
    assert spawn_context().get_start_method() == "spawn"


def test_spawn_worker_starts_idle_and_shuts_down(tmp_path: Path) -> None:
    settings = RecorderWorkerSettings(working_directory=tmp_path)
    worker = RecorderWorkerProcess(settings)
    worker.start()
    try:
        first = worker.get_event(timeout=30)
        assert isinstance(first, WorkerStateChanged)
        assert first.state == WorkerState.IDLE

        worker.send(Shutdown())
        shutdown = worker.get_event(timeout=30)
        assert isinstance(shutdown, WorkerStateChanged)
        assert shutdown.state == WorkerState.SHUTTING_DOWN

        worker.join(timeout=30)
        assert not worker.is_alive()
        assert worker.exitcode == 0
    finally:
        worker.terminate()
        worker.close()
