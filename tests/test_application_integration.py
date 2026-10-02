"""ApplicationController with the real in-process recorder runtime.

The recorder worker runs its real command loop, capture/encode threads,
SegmentRecorder, RingStorage and ReplayAssetBuilder, driven by a fake input
source.  Only the replay controller (mpv) is faked, so no mpv or hardware is
required.
"""

import queue
import time
from collections.abc import Callable
from pathlib import Path

from fake_application import FakeReplayFactory
from fake_worker_input import ScriptedInputFactory, WorkerHarness

from quickreplay.app.state import ApplicationState
from quickreplay.application.controller import ApplicationController
from quickreplay.application.models import ApplicationControllerSettings
from quickreplay.input.models import NdiInputConfig
from quickreplay.worker.settings import RecorderWorkerSettings


class InProcessWorkerHandle:
    """Adapts the Phase 7 in-process worker harness to the WorkerHandle API."""

    def __init__(self, settings: RecorderWorkerSettings, input_factory) -> None:
        self._harness = WorkerHarness(settings, input_factory=input_factory)

    def start(self) -> None:
        self._harness.start()

    def send(self, command) -> None:
        self._harness.send(command)

    def get_event(self, timeout: float | None = None):
        try:
            return self._harness.events.get(timeout=timeout)
        except queue.Empty:
            return None

    def is_alive(self) -> bool:
        return self._harness.thread.is_alive()

    @property
    def exitcode(self) -> int | None:
        return None if self._harness.thread.is_alive() else 0

    def join(self, timeout: float | None = None) -> None:
        self._harness.thread.join(timeout)

    def terminate(self) -> None:
        return None

    def close(self) -> None:
        return None


def _captured_at_least(app: ApplicationController, minimum: int) -> bool:
    metrics = app.snapshot().metrics
    return metrics is not None and metrics.captured_video_frames >= minimum


def _poll_until(
    app: ApplicationController, predicate: Callable[[], bool], timeout: float = 5.0
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.poll(timeout=0.02)
        if predicate():
            return
    raise AssertionError("condition was not met in time")


def test_application_recording_replay_resume(tmp_path: Path) -> None:
    worker_settings = RecorderWorkerSettings(
        working_directory=tmp_path,
        metrics_interval_ns=20_000_000,
        stream_start_timeout_ns=2_000_000_000,
        video_queue_capacity=4096,
        audio_queue_capacity=4096,
    )
    factory = ScriptedInputFactory(duration_ns=1_000_000_000)
    handle = InProcessWorkerHandle(worker_settings, factory)
    replay_factory = FakeReplayFactory()
    app = ApplicationController(
        ApplicationControllerSettings(worker=worker_settings),
        worker_factory=lambda: handle,
        replay_controller_factory=replay_factory,
    )

    app.start()
    assert app.state == ApplicationState.IDLE

    app.start_recording(NdiInputConfig("fake"))
    _poll_until(app, lambda: app.state == ApplicationState.RECORDING)
    assert app.snapshot().stream_info is not None

    _poll_until(app, lambda: _captured_at_least(app, factory.video_frames), timeout=10.0)

    app.request_replay()
    assert app.state == ApplicationState.PREPARING_REPLAY
    _poll_until(app, lambda: app.state == ApplicationState.REPLAY, timeout=10.0)

    asset = app.snapshot().replay_asset
    assert asset is not None
    assert asset.path.exists()
    assert replay_factory.controllers[0].calls[0] == "open"

    app.resume_recording()
    assert app.state == ApplicationState.RESUMING
    _poll_until(app, lambda: app.state == ApplicationState.RECORDING, timeout=10.0)

    assert app.snapshot().replay_asset is None
    assert factory.calls == 2

    app.shutdown()
    assert app.state == ApplicationState.SHUTTING_DOWN
    assert not handle.is_alive()
