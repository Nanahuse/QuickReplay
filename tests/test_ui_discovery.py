"""NDI discovery command forwarding and worker execution."""

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


def test_application_controller_sends_discovery_request() -> None:
    worker = FakeWorker()
    app = ApplicationController(
        ApplicationControllerSettings(),
        worker_factory=lambda: worker,
        replay_controller_factory=FakeReplayFactory(),
    )
    app.start()
    app.poll()
    request_id = app.discover_inputs()

    command = worker.commands_of(DiscoverInputs)[0]
    assert command.request_id == request_id


def test_worker_discovery_callback_has_no_arguments(tmp_path: Path) -> None:
    calls: list[bool] = []

    def discovery() -> tuple:
        calls.append(True)
        return ()

    settings = RecorderWorkerSettings(working_directory=tmp_path, metrics_interval_ns=20_000_000)
    harness = WorkerHarness(settings, input_factory=ScriptedInputFactory(), discovery=discovery)
    try:
        harness.start()
        harness.wait_state(WorkerState.IDLE)
        request_id = uuid4()
        harness.send(DiscoverInputs(request_id))
        harness.wait_event(InputsDiscovered, predicate=lambda event: event.request_id == request_id)
        assert calls == [True]
    finally:
        harness.shutdown()
