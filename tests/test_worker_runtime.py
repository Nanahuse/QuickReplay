"""RecorderWorkerRuntime: state machine, replay lifecycle and error handling."""

import pickle
from fractions import Fraction
from pathlib import Path
from uuid import UUID, uuid4

from fake_worker_input import (
    FakeInputSource,
    ScriptedInputFactory,
    WorkerHarness,
    video_frame,
    video_info,
)

from quickreplay.input.models import (
    NdiInputConfig,
    NdiInputDescriptor,
    StreamInfo,
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
)
from quickreplay.recording.models import WorkerErrorCode, WorkerState
from quickreplay.replay.asset_builder import ReplayAssetBuilder
from quickreplay.replay.errors import ReplayRemuxError
from quickreplay.worker.inputs import InputSourceHandle
from quickreplay.worker.settings import RecorderWorkerSettings

FPS = Fraction(60, 1)


def _settings(tmp_path: Path, **overrides: int) -> RecorderWorkerSettings:
    defaults: dict[str, int] = {
        "metrics_interval_ns": 20_000_000,
        "stream_start_timeout_ns": 2_000_000_000,
        "video_queue_capacity": 4096,
        "audio_queue_capacity": 4096,
    }
    defaults.update(overrides)
    return RecorderWorkerSettings(working_directory=tmp_path, **defaults)


def _start(harness: WorkerHarness) -> UUID:
    harness.start()
    harness.wait_state(WorkerState.IDLE)
    request_id = uuid4()
    harness.send(StartRecording(request_id, NdiInputConfig("fake")))
    harness.wait_state(WorkerState.RECORDING)
    return request_id


def _wait_captured(harness: WorkerHarness, factory: ScriptedInputFactory) -> None:
    harness.wait_event(
        RecordingMetricsUpdated,
        predicate=lambda event: (
            event.metrics.captured_video_frames >= factory.video_frames
            and event.metrics.captured_audio_samples >= factory.audio_samples
        ),
        timeout=10.0,
        description="all frames captured",
    )


def test_stream_started_request_id_protocol() -> None:
    info = StreamInfo(video=video_info(FPS), audio=None)
    assert StreamStarted(info).request_id is None
    request_id = uuid4()
    restored = pickle.loads(pickle.dumps(StreamStarted(info, request_id)))
    assert restored.request_id == request_id


def test_start_recording(tmp_path: Path) -> None:
    factory = ScriptedInputFactory(duration_ns=1_000_000_000)
    harness = WorkerHarness(_settings(tmp_path), input_factory=factory)
    try:
        harness.start()
        harness.wait_state(WorkerState.IDLE)
        request_id = uuid4()
        harness.send(StartRecording(request_id, NdiInputConfig("fake")))
        harness.wait_state(WorkerState.STARTING)
        harness.wait_state(WorkerState.RECORDING)
        started = harness.wait_event(StreamStarted)
        assert started.request_id == request_id
        assert started.stream_info.audio is not None
        assert factory.calls == 1
    finally:
        harness.shutdown()


def test_metrics_are_emitted(tmp_path: Path) -> None:
    factory = ScriptedInputFactory(duration_ns=1_000_000_000)
    harness = WorkerHarness(_settings(tmp_path), input_factory=factory)
    try:
        _start(harness)
        metrics = harness.wait_event(
            RecordingMetricsUpdated,
            predicate=lambda event: event.metrics.captured_video_frames > 0,
            timeout=5.0,
        )
        assert metrics.metrics.input_fps >= 0
        assert metrics.metrics.recording_fps >= 0
    finally:
        harness.shutdown()


def test_prepare_replay_builds_and_cleans_up(tmp_path: Path, probe) -> None:
    factory = ScriptedInputFactory(duration_ns=2_000_000_000)
    settings = _settings(tmp_path)
    harness = WorkerHarness(settings, input_factory=factory)
    try:
        _start(harness)
        _wait_captured(harness, factory)
        request_id = uuid4()
        harness.send(PrepareReplay(request_id))
        harness.wait_state(WorkerState.FREEZING)
        harness.wait_state(WorkerState.FROZEN)
        prepared = harness.wait_event(ReplayPrepared)

        assert prepared.request_id == request_id
        assert prepared.asset.path.exists()
        facts = probe(prepared.asset.path)
        assert facts.decoded_video_frames == factory.video_frames
        assert facts.audio_samples == factory.audio_samples
        assert list(settings.buffer_root.iterdir()) == []
    finally:
        harness.shutdown()


def test_resume_starts_a_new_session(tmp_path: Path) -> None:
    factory = ScriptedInputFactory(duration_ns=1_000_000_000)
    settings = _settings(tmp_path)
    harness = WorkerHarness(settings, input_factory=factory)
    try:
        _start(harness)
        _wait_captured(harness, factory)
        harness.send(PrepareReplay(uuid4()))
        prepared = harness.wait_event(ReplayPrepared)
        replay_path = prepared.asset.path
        assert replay_path.exists()

        request_id = uuid4()
        harness.send(ResumeRecording(request_id))
        harness.wait_state(WorkerState.STARTING)
        harness.wait_state(WorkerState.RECORDING)
        started = harness.wait_event(
            StreamStarted, predicate=lambda event: event.request_id == request_id
        )

        assert factory.calls == 2
        assert factory.sources[0] is not factory.sources[1]
        assert factory.sources[0].close_count >= 1
        assert not replay_path.exists()
        assert started.request_id == request_id
        directories = [path for path in settings.buffer_root.iterdir() if path.is_dir()]
        assert len(directories) == 1
    finally:
        harness.shutdown()


def test_stop_session_cleans_recording_and_allows_restart(tmp_path: Path) -> None:
    factory = ScriptedInputFactory(duration_ns=1_000_000_000)
    settings = _settings(tmp_path)
    harness = WorkerHarness(settings, input_factory=factory)
    try:
        first_start_id = _start(harness)
        _wait_captured(harness, factory)
        first_pipeline = harness.runtime._pipeline
        assert first_pipeline is not None
        first_session = first_pipeline.session
        assert first_session is not None
        first_session_id = first_session.id
        first_epoch_ns = first_session.epoch_ns
        request_id = uuid4()
        harness.send(StopSession(request_id))
        harness.wait_state(WorkerState.IDLE)
        stopped = harness.wait_event(SessionStopped)
        assert stopped.request_id == request_id
        assert list(settings.buffer_root.iterdir()) == []
        assert harness.runtime._config is None
        assert harness.runtime._pipeline is None
        assert factory.sources[0].close_count >= 1

        second_start_id = uuid4()
        assert second_start_id != first_start_id
        harness.send(StartRecording(second_start_id, NdiInputConfig("fake")))
        harness.wait_state(WorkerState.RECORDING)
        restarted = harness.wait_event(
            StreamStarted, predicate=lambda event: event.request_id == second_start_id
        )
        second_pipeline = harness.runtime._pipeline
        assert second_pipeline is not None
        assert second_pipeline is not first_pipeline
        second_session = second_pipeline.session
        assert second_session is not None
        assert second_session.id != first_session_id
        assert second_session.epoch_ns != first_epoch_ns
        assert restarted.request_id == second_start_id
        assert factory.calls == 2
        assert factory.sources[0] is not factory.sources[1]
        assert factory.sources[1].close_count == 0
        assert first_pipeline._metrics is not second_pipeline._metrics
    finally:
        harness.shutdown()


def test_stop_session_cleans_frozen_replay(tmp_path: Path) -> None:
    factory = ScriptedInputFactory(duration_ns=1_000_000_000)
    settings = _settings(tmp_path)
    harness = WorkerHarness(settings, input_factory=factory)
    try:
        _start(harness)
        _wait_captured(harness, factory)
        harness.send(PrepareReplay(uuid4()))
        prepared = harness.wait_event(ReplayPrepared)
        assert prepared.asset.path.exists()

        request_id = uuid4()
        harness.send(StopSession(request_id))
        harness.wait_state(WorkerState.IDLE)
        stopped = harness.wait_event(SessionStopped)
        assert stopped.request_id == request_id
        assert not prepared.asset.path.exists()

        harness.send(StartRecording(uuid4(), NdiInputConfig("fake")))
        harness.wait_state(WorkerState.RECORDING)
    finally:
        harness.shutdown()


def test_change_input_starts_a_new_session(tmp_path: Path) -> None:
    factory = ScriptedInputFactory(duration_ns=1_000_000_000)
    harness = WorkerHarness(_settings(tmp_path), input_factory=factory)
    try:
        _start(harness)
        _wait_captured(harness, factory)
        request_id = uuid4()
        harness.send(ChangeInput(request_id, NdiInputConfig("cam")))
        harness.wait_state(WorkerState.STOPPING)
        harness.wait_state(WorkerState.RECORDING)
        started = harness.wait_event(
            StreamStarted, predicate=lambda event: event.request_id == request_id
        )
        assert factory.calls == 2
        assert started.request_id == request_id
        assert factory.sources[0].close_count >= 1
        # The previous session was fully cleaned up: only the new session
        # directory remains and no writer temporary file is left behind.
        settings = _settings(tmp_path)
        directories = [entry for entry in settings.buffer_root.iterdir() if entry.is_dir()]
        assert len(directories) == 1
        assert list(settings.buffer_root.rglob("*.tmp.mkv")) == []
    finally:
        harness.shutdown()


def test_discover_inputs(tmp_path: Path) -> None:
    descriptor = NdiInputDescriptor("PC (OBS)")
    harness = WorkerHarness(
        _settings(tmp_path),
        input_factory=ScriptedInputFactory(),
        discovery=lambda **_kwargs: (descriptor,),
    )
    try:
        harness.start()
        harness.wait_state(WorkerState.IDLE)
        request_id = uuid4()
        harness.send(DiscoverInputs(request_id))
        event = harness.wait_event(InputsDiscovered)
        assert event.request_id == request_id
        assert event.inputs == (descriptor,)
    finally:
        harness.shutdown()


def test_invalid_commands_are_rejected(tmp_path: Path) -> None:
    factory = ScriptedInputFactory(duration_ns=1_000_000_000)
    harness = WorkerHarness(_settings(tmp_path), input_factory=factory)
    try:
        harness.start()
        harness.wait_state(WorkerState.IDLE)
        request_id = uuid4()
        harness.send(PrepareReplay(request_id))
        error = harness.wait_event(
            WorkerError, predicate=lambda event: event.request_id == request_id
        )
        assert error.code == WorkerErrorCode.INTERNAL_ERROR

        harness.send(StartRecording(uuid4(), NdiInputConfig("fake")))
        harness.wait_state(WorkerState.RECORDING)
        harness.send(ResumeRecording(uuid4()))
        rejected = harness.wait_event(
            WorkerError, predicate=lambda event: event.request_id is not None
        )
        assert rejected.code == WorkerErrorCode.INTERNAL_ERROR
        assert harness.runtime.state == WorkerState.RECORDING
    finally:
        harness.shutdown()


def test_capture_failure_enters_error(tmp_path: Path) -> None:
    def factory(_config) -> InputSourceHandle:
        source = FakeInputSource(
            [video_frame(1_000_000_000, fps=FPS), ValueError("capture exploded")],
            video_stream=video_info(FPS),
        )
        return InputSourceHandle(source=source, supports_audio=False)

    harness = WorkerHarness(_settings(tmp_path), input_factory=factory)
    try:
        harness.start()
        harness.wait_state(WorkerState.IDLE)
        harness.send(StartRecording(uuid4(), NdiInputConfig("fake")))
        harness.wait_state(WorkerState.RECORDING)
        error = harness.wait_event(WorkerError, timeout=5.0)
        harness.wait_state(WorkerState.ERROR)
        assert error.code == WorkerErrorCode.INTERNAL_ERROR
    finally:
        harness.shutdown()


def _failing_remux(segments, tmp_path) -> None:
    raise ReplayRemuxError("injected replay failure")


def test_replay_failure_enters_error(tmp_path: Path) -> None:
    factory = ScriptedInputFactory(duration_ns=1_000_000_000)
    settings = _settings(tmp_path)
    harness = WorkerHarness(
        settings,
        input_factory=factory,
        builder_factory=lambda: ReplayAssetBuilder(remux=_failing_remux),
    )
    try:
        _start(harness)
        _wait_captured(harness, factory)
        request_id = uuid4()
        harness.send(PrepareReplay(request_id))
        error = harness.wait_event(WorkerError, timeout=5.0)
        harness.wait_state(WorkerState.ERROR)
        assert error.code == WorkerErrorCode.REPLAY_ASSET_FAILED
        assert error.request_id == request_id
        assert not any(isinstance(event, ReplayPrepared) for event in harness.seen)
        assert not (settings.replay_root / str(request_id)).exists()
    finally:
        harness.shutdown()


def test_shutdown_during_recording(tmp_path: Path) -> None:
    factory = ScriptedInputFactory(duration_ns=2_000_000_000)
    settings = _settings(tmp_path)
    harness = WorkerHarness(settings, input_factory=factory)
    harness.start()
    harness.wait_state(WorkerState.IDLE)
    harness.send(StartRecording(uuid4(), NdiInputConfig("fake")))
    harness.wait_state(WorkerState.RECORDING)
    harness.send(Shutdown())
    harness.wait_state(WorkerState.SHUTTING_DOWN)
    harness.join(timeout=10.0)

    assert not harness.thread.is_alive()
    assert factory.sources[0].close_count >= 1
    assert list(settings.buffer_root.iterdir()) == []
    assert list(settings.buffer_root.rglob("*.tmp.mkv")) == []


def test_shutdown_after_replay_removes_asset(tmp_path: Path) -> None:
    factory = ScriptedInputFactory(duration_ns=1_000_000_000)
    settings = _settings(tmp_path)
    harness = WorkerHarness(settings, input_factory=factory)
    harness.start()
    harness.wait_state(WorkerState.IDLE)
    harness.send(StartRecording(uuid4(), NdiInputConfig("fake")))
    harness.wait_state(WorkerState.RECORDING)
    _wait_captured(harness, factory)
    harness.send(PrepareReplay(uuid4()))
    prepared = harness.wait_event(ReplayPrepared)
    replay_path = prepared.asset.path

    harness.send(Shutdown())
    harness.wait_state(WorkerState.SHUTTING_DOWN)
    harness.join(timeout=10.0)

    assert not harness.thread.is_alive()
    assert not replay_path.exists()
