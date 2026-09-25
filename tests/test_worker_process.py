"""Spawn process integration for the recorder worker."""

import pickle
from pathlib import Path
from types import SimpleNamespace

import pytest

from quickreplay.recording.commands import Shutdown
from quickreplay.recording.events import WorkerStateChanged
from quickreplay.recording.models import WorkerState
from quickreplay.worker import process
from quickreplay.worker.process import (
    RecorderWorkerProcess,
    spawn_context,
    worker_process_main,
)
from quickreplay.worker.settings import RecorderWorkerSettings


def test_worker_process_main_is_a_module_level_function() -> None:
    restored = pickle.loads(pickle.dumps(worker_process_main))
    assert restored is worker_process_main


def test_worker_process_owns_ndi_runtime_until_runtime_returns(monkeypatch, tmp_path: Path) -> None:
    calls = []

    class FakeBackend:
        def initialize(self) -> None:
            calls.append("ndi.initialize")

        def shutdown(self) -> None:
            calls.append("ndi.shutdown")

    class FakeRuntime:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def run(self) -> None:
            calls.append("runtime.run")

    monkeypatch.setattr(process, "PyNdiBackend", FakeBackend)
    monkeypatch.setattr(process, "RecorderWorkerRuntime", FakeRuntime)

    worker_process_main(
        object(),
        SimpleNamespace(put=lambda _event: None),
        RecorderWorkerSettings(working_directory=tmp_path),
    )

    assert calls == ["ndi.initialize", "runtime.run", "ndi.shutdown"]


def test_worker_process_releases_ndi_runtime_when_runtime_raises(
    monkeypatch, tmp_path: Path
) -> None:
    calls = []

    class FakeBackend:
        def initialize(self) -> None:
            calls.append("ndi.initialize")

        def shutdown(self) -> None:
            calls.append("ndi.shutdown")

    class FakeRuntime:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def run(self) -> None:
            calls.append("runtime.run")
            raise RuntimeError("worker failed")

    monkeypatch.setattr(process, "PyNdiBackend", FakeBackend)
    monkeypatch.setattr(process, "RecorderWorkerRuntime", FakeRuntime)

    with pytest.raises(RuntimeError, match="worker failed"):
        worker_process_main(
            object(),
            SimpleNamespace(put=lambda _event: None),
            RecorderWorkerSettings(working_directory=tmp_path),
        )

    assert calls == ["ndi.initialize", "runtime.run", "ndi.shutdown"]


def test_worker_process_does_not_shutdown_if_ndi_initialization_fails(
    monkeypatch, tmp_path: Path
) -> None:
    calls = []

    class FakeBackend:
        def initialize(self) -> None:
            calls.append("ndi.initialize")
            raise RuntimeError("NDI initialization failed")

        def shutdown(self) -> None:
            calls.append("ndi.shutdown")

    class FakeRuntime:
        def __init__(self, *_args, **_kwargs) -> None:
            calls.append("runtime.create")

    monkeypatch.setattr(process, "PyNdiBackend", FakeBackend)
    monkeypatch.setattr(process, "RecorderWorkerRuntime", FakeRuntime)

    with pytest.raises(RuntimeError, match="NDI initialization failed"):
        worker_process_main(
            object(),
            SimpleNamespace(put=lambda _event: None),
            RecorderWorkerSettings(working_directory=tmp_path),
        )

    assert calls == ["ndi.initialize"]


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
