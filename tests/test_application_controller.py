"""ApplicationController: lifecycle, correlation, delegation and shutdown."""

from fractions import Fraction
from pathlib import Path
from uuid import uuid4

import pytest
from fake_application import (
    FakeReplayFactory,
    FakeWorker,
    SequenceRequestIds,
)

from quickreplay.app.state import ApplicationState
from quickreplay.application.controller import ApplicationController
from quickreplay.application.errors import InvalidApplicationStateError, WorkerStartupError
from quickreplay.application.events import (
    ApplicationError,
    ApplicationStateChanged,
    InputsChanged,
    RecordingMetricsChanged,
    RecordingStarted,
    ReplayStarted,
)
from quickreplay.application.models import ApplicationControllerSettings
from quickreplay.input.models import (
    AudioStreamInfo,
    CameraInputConfig,
    NdiInputConfig,
    NdiInputDescriptor,
    StreamInfo,
    VideoStreamInfo,
)
from quickreplay.recording.commands import (
    ChangeInput,
    DiscoverInputs,
    PrepareReplay,
    ResumeRecording,
    Shutdown,
    StartRecording,
    StopSession,
)
from quickreplay.recording.events import (
    InputsDiscovered,
    RecordingMetricsUpdated,
    ReplayPrepared,
    SessionStopped,
    StreamStarted,
    WorkerError,
    WorkerStateChanged,
)
from quickreplay.recording.models import RecordingMetrics, WorkerErrorCode, WorkerState
from quickreplay.replay.errors import MpvProcessExitedError, MpvStartupError
from quickreplay.replay.models import ReplayAsset, frame_difference

FPS = Fraction(60, 1)


def _info(fps: Fraction = FPS) -> StreamInfo:
    return StreamInfo(
        video=VideoStreamInfo(64, 36, fps, "BGR24"),
        audio=AudioStreamInfo(48000, 2),
    )


def _metrics(frames: int = 10) -> RecordingMetrics:
    return RecordingMetrics(
        captured_video_frames=frames,
        recorded_video_frames=frames,
        captured_audio_samples=0,
        recorded_audio_samples=0,
        video_queue_drops=0,
        audio_queue_drops=0,
        buffer_duration_ns=1_000_000_000,
        segment_count=1,
        input_fps=60.0,
        recording_fps=60.0,
    )


def _asset() -> ReplayAsset:
    return ReplayAsset(Path("replay.mkv"), 1_000_000_000, FPS)


def _app(
    worker: FakeWorker,
    replay_factory: FakeReplayFactory | None = None,
    *,
    request_id_factory=uuid4,
    settings: ApplicationControllerSettings | None = None,
) -> ApplicationController:
    return ApplicationController(
        settings or ApplicationControllerSettings(),
        worker_factory=lambda: worker,
        replay_controller_factory=replay_factory or FakeReplayFactory(),
        request_id_factory=request_id_factory,
    )


def _to_recording(
    worker: FakeWorker,
    replay_factory: FakeReplayFactory | None = None,
    **kwargs,
) -> ApplicationController:
    app = _app(worker, replay_factory, **kwargs)
    app.start()
    app.poll()
    app.start_recording(NdiInputConfig("fake"))
    worker.push(StreamStarted(stream_info=_info(), request_id=None))
    app.poll()
    assert app.state == ApplicationState.RECORDING
    return app


def _to_replay(
    worker: FakeWorker, replay_factory: FakeReplayFactory, replay_id
) -> ApplicationController:
    app = _to_recording(worker, replay_factory, request_id_factory=SequenceRequestIds(replay_id))
    app.request_replay()
    worker.push(ReplayPrepared(request_id=replay_id, asset=_asset()))
    app.poll()
    assert app.state == ApplicationState.REPLAY
    return app


def test_start_reaches_idle() -> None:
    worker = FakeWorker()
    app = _app(worker)

    app.start()

    assert app.state == ApplicationState.IDLE
    assert worker.started
    events = app.poll()
    assert ApplicationStateChanged(ApplicationState.IDLE) in events


def test_double_start_is_rejected() -> None:
    worker = FakeWorker()
    app = _app(worker)
    app.start()
    with pytest.raises(InvalidApplicationStateError):
        app.start()


def test_start_timeout_enters_error() -> None:
    worker = FakeWorker(auto_idle=False)
    settings = ApplicationControllerSettings(worker_start_timeout_seconds=0.05)
    app = _app(worker, settings=settings)

    with pytest.raises(WorkerStartupError):
        app.start()

    assert app.state == ApplicationState.ERROR


def test_start_process_exit_enters_error() -> None:
    worker = FakeWorker(auto_idle=False)
    worker.die(2)
    app = _app(worker)

    with pytest.raises(WorkerStartupError):
        app.start()

    assert app.state == ApplicationState.ERROR


def test_start_recording() -> None:
    worker = FakeWorker()
    app = _app(worker)
    app.start()
    app.poll()

    app.start_recording(NdiInputConfig("fake"))

    assert app.state == ApplicationState.STARTING
    assert worker.commands_of(StartRecording)

    worker.push(StreamStarted(stream_info=_info(), request_id=None))
    events = app.poll()

    assert app.state == ApplicationState.RECORDING
    assert app.snapshot().stream_info == _info()
    assert any(isinstance(event, RecordingStarted) for event in events)


def test_replay_lifecycle() -> None:
    replay_id = uuid4()
    worker = FakeWorker()
    replay_factory = FakeReplayFactory()
    app = _to_recording(worker, replay_factory, request_id_factory=SequenceRequestIds(replay_id))

    app.request_replay()

    assert app.state == ApplicationState.PREPARING_REPLAY
    prepared = worker.commands_of(PrepareReplay)
    assert prepared and prepared[0].request_id == replay_id

    worker.push(ReplayPrepared(request_id=replay_id, asset=_asset()))
    events = app.poll()

    assert app.state == ApplicationState.REPLAY
    assert replay_factory.controllers[0].calls[0] == "open"
    assert app.snapshot().replay_asset == _asset()
    assert any(isinstance(event, ReplayStarted) for event in events)


def test_stale_replay_prepared_is_ignored() -> None:
    replay_id = uuid4()
    worker = FakeWorker()
    replay_factory = FakeReplayFactory()
    app = _to_recording(worker, replay_factory, request_id_factory=SequenceRequestIds(replay_id))
    app.request_replay()

    worker.push(ReplayPrepared(request_id=uuid4(), asset=_asset()))
    app.poll()

    assert app.state == ApplicationState.PREPARING_REPLAY
    assert replay_factory.controllers == []

    worker.push(ReplayPrepared(request_id=replay_id, asset=_asset()))
    app.poll()

    assert app.state == ApplicationState.REPLAY


def test_replay_open_failure_enters_error() -> None:
    replay_id = uuid4()
    worker = FakeWorker()
    replay_factory = FakeReplayFactory(open_error=MpvStartupError("mpv missing"))
    app = _to_recording(worker, replay_factory, request_id_factory=SequenceRequestIds(replay_id))
    app.request_replay()

    worker.push(ReplayPrepared(request_id=replay_id, asset=_asset()))
    events = app.poll()

    assert app.state == ApplicationState.ERROR
    assert replay_factory.controllers[0].calls == ["open", "close"]
    assert any(isinstance(event, ApplicationError) for event in events)


def test_stop_session_from_recording_waits_for_worker_completion() -> None:
    worker = FakeWorker()
    app = _to_recording(worker)

    request_id = app.stop_session()
    assert app.state == ApplicationState.RECORDING
    assert worker.commands_of(StopSession)[0].request_id == request_id

    worker.push(SessionStopped(request_id=request_id))
    events = app.poll()

    assert app.state == ApplicationState.IDLE
    assert app.stream_info is None
    assert app.snapshot().metrics is None
    assert any(isinstance(event, ApplicationStateChanged) for event in events)


def test_stop_session_from_replay_closes_without_resuming() -> None:
    worker = FakeWorker()
    replay_factory = FakeReplayFactory()
    replay_id = uuid4()
    app = _to_replay(worker, replay_factory, replay_id)
    replay = replay_factory.controllers[0]

    request_id = app.stop_session()
    assert replay.calls[-1] == "close"
    assert not worker.commands_of(ResumeRecording)
    assert worker.commands_of(StopSession)[0].request_id == request_id
    assert app.state == ApplicationState.REPLAY

    worker.push(SessionStopped(request_id=request_id))
    app.poll()

    assert app.state == ApplicationState.IDLE
    assert app.replay_asset is None


def test_stop_session_is_rejected_during_replay_preparation() -> None:
    worker = FakeWorker()
    app = _to_recording(worker)
    app.request_replay()

    with pytest.raises(InvalidApplicationStateError):
        app.stop_session()


def test_resume_lifecycle() -> None:
    replay_id = uuid4()
    worker = FakeWorker()
    replay_factory = FakeReplayFactory()
    app = _to_replay(worker, replay_factory, replay_id)

    app.resume_recording()

    assert app.state == ApplicationState.RESUMING
    assert replay_factory.controllers[0].calls[-1] == "close"
    resumes = worker.commands_of(ResumeRecording)
    assert resumes

    worker.push(StreamStarted(stream_info=_info(), request_id=resumes[0].request_id))
    app.poll()

    assert app.state == ApplicationState.RECORDING
    assert app.snapshot().replay_asset is None


def test_replay_is_closed_before_resume_is_sent() -> None:
    order: list[tuple[str, str | None]] = []
    replay_id = uuid4()
    worker = FakeWorker()
    worker.order = order
    replay_factory = FakeReplayFactory(order=order)
    app = _to_recording(worker, replay_factory, request_id_factory=SequenceRequestIds(replay_id))
    app.request_replay()
    worker.push(ReplayPrepared(request_id=replay_id, asset=_asset()))
    app.poll()

    app.resume_recording()

    assert order.index(("replay.close", None)) < order.index(("worker.send", "ResumeRecording"))


def test_stale_resume_response_is_ignored() -> None:
    replay_id = uuid4()
    worker = FakeWorker()
    replay_factory = FakeReplayFactory()
    app = _to_replay(worker, replay_factory, replay_id)
    app.resume_recording()

    worker.push(StreamStarted(stream_info=_info(), request_id=uuid4()))
    app.poll()
    assert app.state == ApplicationState.RESUMING

    resume_id = worker.commands_of(ResumeRecording)[0].request_id
    worker.push(StreamStarted(stream_info=_info(), request_id=resume_id))
    app.poll()
    assert app.state == ApplicationState.RECORDING


def test_change_input() -> None:
    change_id = uuid4()
    worker = FakeWorker()
    app = _to_recording(worker, request_id_factory=SequenceRequestIds(change_id))
    new_info = _info()

    returned = app.change_input(CameraInputConfig("cam", 0, "any"))

    assert returned == change_id
    assert app.state == ApplicationState.STARTING
    changes = worker.commands_of(ChangeInput)
    assert changes and changes[0].request_id == change_id

    worker.push(StreamStarted(stream_info=new_info, request_id=change_id))
    app.poll()

    assert app.state == ApplicationState.RECORDING
    assert app.snapshot().stream_info == new_info


def test_stale_change_input_response_does_not_override() -> None:
    change_id = uuid4()
    worker = FakeWorker()
    app = _to_recording(worker, request_id_factory=SequenceRequestIds(change_id))
    original = app.snapshot().stream_info
    app.change_input(CameraInputConfig("cam", 0, "any"))

    worker.push(StreamStarted(stream_info=_info(), request_id=uuid4()))
    app.poll()

    assert app.state == ApplicationState.STARTING
    assert app.snapshot().stream_info == original


def test_discovery_does_not_change_state() -> None:
    discovery_id = uuid4()
    worker = FakeWorker()
    app = _to_recording(worker, request_id_factory=SequenceRequestIds(discovery_id))
    descriptor = NdiInputDescriptor("PC (OBS)")

    returned = app.discover_inputs()

    assert returned == discovery_id
    assert app.state == ApplicationState.RECORDING
    assert worker.commands_of(DiscoverInputs)

    worker.push(InputsDiscovered(request_id=discovery_id, inputs=(descriptor,)))
    events = app.poll()

    assert app.state == ApplicationState.RECORDING
    assert InputsChanged(request_id=discovery_id, inputs=(descriptor,)) in events


def test_discovery_error_is_non_fatal() -> None:
    discovery_id = uuid4()
    worker = FakeWorker()
    app = _to_recording(worker, request_id_factory=SequenceRequestIds(discovery_id))
    app.discover_inputs()

    worker.push(
        WorkerError(
            code=WorkerErrorCode.INTERNAL_ERROR,
            message="discovery failed",
            request_id=discovery_id,
        )
    )
    events = app.poll()

    assert app.state == ApplicationState.RECORDING
    assert any(isinstance(event, ApplicationError) for event in events)


def test_metrics_are_recorded_and_emitted() -> None:
    worker = FakeWorker()
    app = _to_recording(worker)
    metrics = _metrics(120)

    worker.push(RecordingMetricsUpdated(metrics=metrics))
    events = app.poll()

    assert app.snapshot().metrics == metrics
    assert RecordingMetricsChanged(metrics=metrics) in events


def test_metrics_after_replay_request_are_ignored() -> None:
    replay_id = uuid4()
    worker = FakeWorker()
    replay_factory = FakeReplayFactory()
    app = _to_recording(worker, replay_factory, request_id_factory=SequenceRequestIds(replay_id))
    worker.push(RecordingMetricsUpdated(metrics=_metrics(50)))
    app.poll()
    app.request_replay()

    worker.push(RecordingMetricsUpdated(metrics=_metrics(999)))
    app.poll()

    assert app.snapshot().metrics is None


def test_worker_error_enters_error() -> None:
    worker = FakeWorker()
    app = _to_recording(worker)

    worker.push(WorkerError(code=WorkerErrorCode.CAPTURE_FAILED, message="capture failed"))
    events = app.poll()

    assert app.state == ApplicationState.ERROR
    assert any(isinstance(event, ApplicationError) for event in events)


def test_worker_error_state_enters_error() -> None:
    worker = FakeWorker()
    app = _to_recording(worker)

    worker.push(WorkerStateChanged(state=WorkerState.ERROR))
    app.poll()

    assert app.state == ApplicationState.ERROR


def test_worker_process_death_enters_error() -> None:
    worker = FakeWorker()
    app = _to_recording(worker)

    worker.die(3)
    app.poll()

    assert app.state == ApplicationState.ERROR
    assert "3" in (app.snapshot().error_message or "")


def test_mpv_unexpected_exit_resumes_recording() -> None:
    replay_id = uuid4()
    worker = FakeWorker()
    replay_factory = FakeReplayFactory()
    app = _to_replay(worker, replay_factory, replay_id)
    replay_factory.controllers[0].dead = True

    app.poll()

    assert app.state == ApplicationState.RESUMING
    assert replay_factory.controllers[0].calls[-1] == "close"
    resumes = worker.commands_of(ResumeRecording)
    assert resumes

    worker.push(StreamStarted(stream_info=_info(), request_id=resumes[0].request_id))
    app.poll()
    assert app.state == ApplicationState.RECORDING


def test_replay_operation_on_dead_mpv_resumes() -> None:
    replay_id = uuid4()
    worker = FakeWorker()
    replay_factory = FakeReplayFactory()
    app = _to_replay(worker, replay_factory, replay_id)
    replay_factory.controllers[0].dead = True

    with pytest.raises(MpvProcessExitedError):
        app.play()

    assert app.state == ApplicationState.RESUMING


def test_resume_failure_enters_error() -> None:
    replay_id = uuid4()
    worker = FakeWorker()
    replay_factory = FakeReplayFactory()
    app = _to_replay(worker, replay_factory, replay_id)
    app.resume_recording()
    resume_id = worker.commands_of(ResumeRecording)[0].request_id

    worker.push(
        WorkerError(
            code=WorkerErrorCode.INTERNAL_ERROR, message="resume failed", request_id=resume_id
        )
    )
    app.poll()

    assert app.state == ApplicationState.ERROR


def test_replay_operations_are_delegated() -> None:
    replay_id = uuid4()
    worker = FakeWorker()
    replay_factory = FakeReplayFactory()
    app = _to_replay(worker, replay_factory, replay_id)
    replay = replay_factory.controllers[0]

    app.play()
    app.pause()
    app.step_forward()
    app.step_backward()
    app.seek_frames(5)
    app.seek_absolute_ns(1_000_000)

    assert replay.calls == [
        "open",
        "play",
        "pause",
        "step_forward",
        "step_backward",
        ("seek_frames", 5),
        ("seek_absolute_ns", 1_000_000),
    ]

    replay.position = 2_000_000_000
    assert app.replay_position_ns() == 2_000_000_000
    point = app.set_point()
    assert point.position_ns == 2_000_000_000
    replay.position = 2_050_000_000
    assert app.time_difference_ns(point) == 50_000_000
    assert app.frame_difference(point) == frame_difference(2_050_000_000, 2_000_000_000, FPS)


def test_invalid_operations_are_rejected() -> None:
    replay_id = uuid4()
    worker = FakeWorker()
    replay_factory = FakeReplayFactory()
    app = _app(worker, replay_factory, request_id_factory=SequenceRequestIds(replay_id))

    with pytest.raises(InvalidApplicationStateError):
        app.request_replay()

    app.start()
    app.poll()
    with pytest.raises(InvalidApplicationStateError):
        app.resume_recording()

    app.start_recording(NdiInputConfig("fake"))
    worker.push(StreamStarted(stream_info=_info(), request_id=None))
    app.poll()
    with pytest.raises(InvalidApplicationStateError):
        app.play()
    with pytest.raises(InvalidApplicationStateError):
        app.resume_recording()

    app.request_replay()
    with pytest.raises(InvalidApplicationStateError):
        app.request_replay()

    worker.push(ReplayPrepared(request_id=replay_id, asset=_asset()))
    app.poll()
    with pytest.raises(InvalidApplicationStateError):
        app.change_input(CameraInputConfig("cam", 0, "any"))

    app.resume_recording()
    with pytest.raises(InvalidApplicationStateError):
        app.resume_recording()
    with pytest.raises(InvalidApplicationStateError):
        app.play()


def test_shutdown_from_idle() -> None:
    worker = FakeWorker()
    app = _app(worker)
    app.start()
    app.poll()

    app.shutdown()

    assert app.state == ApplicationState.SHUTTING_DOWN
    assert worker.commands_of(Shutdown)
    assert worker.join_calls >= 1
    assert worker.closed

    app.shutdown()  # idempotent
    assert worker.join_calls == 1


def test_shutdown_from_recording_is_graceful() -> None:
    worker = FakeWorker()
    app = _to_recording(worker)

    app.shutdown()

    assert app.state == ApplicationState.SHUTTING_DOWN
    assert worker.terminate_calls == 0
    assert worker.closed


def test_shutdown_terminates_when_worker_does_not_exit() -> None:
    worker = FakeWorker(exit_on_shutdown=False)
    app = _to_recording(worker)

    app.shutdown()

    assert worker.terminate_calls == 1


def test_shutdown_from_replay_closes_replay_first() -> None:
    order: list[tuple[str, str | None]] = []
    replay_id = uuid4()
    worker = FakeWorker()
    worker.order = order
    replay_factory = FakeReplayFactory(order=order)
    app = _to_recording(worker, replay_factory, request_id_factory=SequenceRequestIds(replay_id))
    app.request_replay()
    worker.push(ReplayPrepared(request_id=replay_id, asset=_asset()))
    app.poll()

    app.shutdown()

    assert order.index(("replay.close", None)) < order.index(("worker.send", "Shutdown"))


def test_shutdown_during_preparing_replay_ignores_late_prepared() -> None:
    replay_id = uuid4()
    worker = FakeWorker()
    replay_factory = FakeReplayFactory()
    app = _to_recording(worker, replay_factory, request_id_factory=SequenceRequestIds(replay_id))
    app.request_replay()

    app.shutdown()
    worker.push(ReplayPrepared(request_id=replay_id, asset=_asset()))
    app.poll()

    assert app.state == ApplicationState.SHUTTING_DOWN
    assert replay_factory.controllers == []


def test_shutdown_during_resuming_ignores_late_stream_started() -> None:
    replay_id = uuid4()
    worker = FakeWorker()
    replay_factory = FakeReplayFactory()
    app = _to_replay(worker, replay_factory, replay_id)
    app.resume_recording()
    resume_id = worker.commands_of(ResumeRecording)[0].request_id

    app.shutdown()
    worker.push(StreamStarted(stream_info=_info(), request_id=resume_id))
    app.poll()

    assert app.state == ApplicationState.SHUTTING_DOWN
