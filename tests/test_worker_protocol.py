"""Tests for the worker command / event protocol (picklable value objects)."""

import pickle
from fractions import Fraction
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from quickreplay.input.models import (
    AudioStreamInfo,
    CameraInputConfig,
    CameraInputDescriptor,
    CameraMode,
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
    WorkerCommand,
)
from quickreplay.recording.events import (
    InputsDiscovered,
    RecordingMetricsUpdated,
    ReplayPrepared,
    StreamStarted,
    WorkerError,
    WorkerEvent,
    WorkerStateChanged,
)
from quickreplay.recording.models import (
    RecordingMetrics,
    WorkerErrorCode,
    WorkerState,
)
from quickreplay.replay.models import ReplayAsset


def _stream_info() -> StreamInfo:
    return StreamInfo(
        video=VideoStreamInfo(1920, 1080, Fraction(60000, 1001), "UYVY"),
        audio=AudioStreamInfo(48000, 2),
    )


def _metrics() -> RecordingMetrics:
    return RecordingMetrics(
        captured_video_frames=1800,
        recorded_video_frames=1799,
        captured_audio_samples=1_440_000,
        recorded_audio_samples=1_439_000,
        video_queue_drops=0,
        audio_queue_drops=0,
        buffer_duration_ns=30_000_000_000,
        segment_count=15,
        input_fps=59.94,
        recording_fps=60.0,
    )


def _camera_config() -> CameraInputConfig:
    return CameraInputConfig(
        device_name="USB Camera",
        device_index=0,
        backend="msmf",
        mode=CameraMode(1280, 720, Fraction(30, 1)),
    )


def _commands() -> list[WorkerCommand]:
    request_id = uuid4()
    return [
        StartRecording(input_config=NdiInputConfig("PC-A (OBS)")),
        PrepareReplay(request_id=request_id),
        ResumeRecording(request_id=request_id),
        ChangeInput(request_id=request_id, input_config=_camera_config()),
        DiscoverInputs(request_id=request_id),
        Shutdown(),
    ]


def _events() -> list[WorkerEvent]:
    request_id = uuid4()
    return [
        WorkerStateChanged(state=WorkerState.RECORDING),
        InputsDiscovered(
            request_id=request_id,
            inputs=(
                NdiInputDescriptor("PC-A (OBS)"),
                CameraInputDescriptor("USB Camera", 0),
            ),
        ),
        StreamStarted(stream_info=_stream_info()),
        RecordingMetricsUpdated(metrics=_metrics()),
        ReplayPrepared(
            request_id=request_id,
            asset=ReplayAsset(Path("replay.mkv"), 30_000_000_000, Fraction(60, 1)),
        ),
        WorkerError(
            code=WorkerErrorCode.ENCODER_FAILED, message="encoder failed", request_id=request_id
        ),
        WorkerError(code=WorkerErrorCode.INTERNAL_ERROR, message="no request"),
    ]


@pytest.mark.parametrize("command", _commands())
def test_command_pickle_round_trip(command: WorkerCommand) -> None:
    restored = pickle.loads(pickle.dumps(command))
    assert restored == command
    assert type(restored) is type(command)


@pytest.mark.parametrize("event", _events())
def test_event_pickle_round_trip(event: WorkerEvent) -> None:
    restored = pickle.loads(pickle.dumps(event))
    assert restored == event
    assert type(restored) is type(event)


def test_all_command_types_are_represented() -> None:
    assert {type(command) for command in _commands()} == {
        StartRecording,
        PrepareReplay,
        ResumeRecording,
        ChangeInput,
        DiscoverInputs,
        Shutdown,
    }


def test_all_event_types_are_represented() -> None:
    assert {type(event) for event in _events()} == {
        WorkerStateChanged,
        InputsDiscovered,
        StreamStarted,
        RecordingMetricsUpdated,
        ReplayPrepared,
        WorkerError,
    }


def test_request_id_is_preserved() -> None:
    request_id = uuid4()
    assert PrepareReplay(request_id).request_id == request_id
    assert ResumeRecording(request_id).request_id == request_id
    assert ChangeInput(request_id, NdiInputConfig("x")).request_id == request_id
    assert DiscoverInputs(request_id).request_id == request_id

    asset = ReplayAsset(Path("replay.mkv"), 1, Fraction(60, 1))
    prepared = ReplayPrepared(request_id, asset)
    assert prepared.request_id == request_id

    discovered = InputsDiscovered(request_id, (NdiInputDescriptor("x"),))
    assert discovered.request_id == request_id

    error = WorkerError(WorkerErrorCode.INTERNAL_ERROR, "boom", request_id)
    assert error.request_id == request_id
    assert WorkerError(WorkerErrorCode.INTERNAL_ERROR, "boom").request_id is None


def test_pickled_request_id_is_a_uuid() -> None:
    request_id = uuid4()
    restored = pickle.loads(pickle.dumps(PrepareReplay(request_id)))
    assert isinstance(restored.request_id, UUID)
    assert restored.request_id == request_id
