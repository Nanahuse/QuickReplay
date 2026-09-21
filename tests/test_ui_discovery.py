"""Backend-aware discovery: command forwarding and worker execution."""

from pathlib import Path
from uuid import uuid4

from fake_application import FakeReplayFactory, FakeWorker
from fake_worker_input import ScriptedInputFactory, WorkerHarness

from quickreplay.application.controller import ApplicationController
from quickreplay.application.models import ApplicationControllerSettings
from quickreplay.recording.commands import DiscoverInputs
from quickreplay.recording.events import InputsDiscovered
from quickreplay.recording.models import WorkerState
from quickreplay.worker.settings import RecorderWorkerSettings


def test_application_controller_forwards_camera_backend() -> None:
    worker = FakeWorker()
    app = ApplicationController(
        ApplicationControllerSettings(),
        worker_factory=lambda: worker,
        replay_controller_factory=FakeReplayFactory(),
    )
    app.start()
    app.poll()

    app.discover_inputs(camera_backend="dshow")
    app.discover_inputs()

    commands = worker.commands_of(DiscoverInputs)
    assert commands[0].camera_backend == "dshow"
    assert commands[1].camera_backend == "any"


def test_worker_discovery_uses_camera_backend(tmp_path: Path) -> None:
    seen: list[str] = []

    def discovery(*, camera_backend: str = "any") -> tuple:
        seen.append(camera_backend)
        return ()

    settings = RecorderWorkerSettings(working_directory=tmp_path, metrics_interval_ns=20_000_000)
    harness = WorkerHarness(settings, input_factory=ScriptedInputFactory(), discovery=discovery)
    try:
        harness.start()
        harness.wait_state(WorkerState.IDLE)

        request_id = uuid4()
        harness.send(DiscoverInputs(request_id, camera_backend="dshow"))
        harness.wait_event(InputsDiscovered, predicate=lambda event: event.request_id == request_id)

        default_id = uuid4()
        harness.send(DiscoverInputs(default_id))
        harness.wait_event(InputsDiscovered, predicate=lambda event: event.request_id == default_id)

        assert seen == ["dshow", "any"]
    finally:
        harness.shutdown()
