"""UiSession: discovery correlation, selection, persistence and view state."""

import asyncio
from dataclasses import replace
from fractions import Fraction
from pathlib import Path
from uuid import uuid4

from fake_ui import FakeBridge

from quickreplay.app.state import ApplicationState
from quickreplay.application.events import (
    ApplicationError,
    InputsChanged,
    RecordingStarted,
)
from quickreplay.application.models import ApplicationSnapshot
from quickreplay.configuration.errors import ConfigurationWriteError
from quickreplay.configuration.models import QuickReplayConfig, RecordingConfig
from quickreplay.configuration.store import ConfigurationStore
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
from quickreplay.recording.models import RecordingMetrics
from quickreplay.ui.session import CAMERA_KIND, UiSession

FPS = Fraction(60, 1)


def _stream_info() -> StreamInfo:
    return StreamInfo(VideoStreamInfo(1920, 1080, FPS, "UYVY"), AudioStreamInfo(48000, 2))


def _metrics() -> RecordingMetrics:
    return RecordingMetrics(
        captured_video_frames=100,
        recorded_video_frames=100,
        captured_audio_samples=0,
        recorded_audio_samples=0,
        video_queue_drops=0,
        audio_queue_drops=0,
        buffer_duration_ns=30_000_000_000,
        segment_count=15,
        input_fps=60.0,
        recording_fps=60.0,
    )


class _FailingStore(ConfigurationStore):
    def save(self, config: QuickReplayConfig) -> None:
        raise ConfigurationWriteError("disk full")


def _session(
    tmp_path: Path,
    *,
    config: QuickReplayConfig | None = None,
    store: ConfigurationStore | None = None,
    bridge: FakeBridge | None = None,
) -> tuple[UiSession, FakeBridge, ConfigurationStore]:
    active_bridge = bridge or FakeBridge()
    active_store = store or ConfigurationStore(tmp_path / "config.json")
    return (
        UiSession(active_bridge, active_store, config or QuickReplayConfig()),
        active_bridge,
        active_store,
    )


async def _discover(session: UiSession, bridge: FakeBridge, inputs: tuple) -> None:
    bridge.events = [InputsChanged(request_id=bridge.next_discovery_id, inputs=inputs)]
    bridge.snapshot_value = ApplicationSnapshot(state=ApplicationState.IDLE)
    await session.poll()


def test_start_discovers_inputs(tmp_path: Path) -> None:
    session, bridge, _ = _session(tmp_path)

    asyncio.run(session.start())

    assert bridge.started
    assert bridge.discovery_requests == ["any"]


def test_discovery_resolves_and_selects_first_input(tmp_path: Path) -> None:
    session, bridge, _ = _session(tmp_path)
    asyncio.run(session.start())
    asyncio.run(_discover(session, bridge, (NdiInputDescriptor("OBS"),)))

    state = session.view_state()
    assert state.input_options[0].label == "OBS"
    assert state.selected_key is not None
    assert state.controls.start_enabled
    assert not state.discovering


def test_stale_discovery_is_ignored(tmp_path: Path) -> None:
    session, bridge, _ = _session(tmp_path)
    asyncio.run(session.start())

    bridge.events = [InputsChanged(request_id=uuid4(), inputs=(NdiInputDescriptor("Old"),))]
    asyncio.run(session.poll())

    assert session.view_state().input_options == ()
    assert session.view_state().discovering  # still waiting for the current request


def test_saved_ndi_is_restored(tmp_path: Path) -> None:
    config = QuickReplayConfig(input=NdiInputConfig("Studio"))
    session, bridge, _ = _session(tmp_path, config=config)
    asyncio.run(session.start())
    asyncio.run(
        _discover(
            session,
            bridge,
            (NdiInputDescriptor("Other"), NdiInputDescriptor("Studio")),
        )
    )

    state = session.view_state()
    assert state.selected_key == "ndi:Studio"
    assert state.controls.start_enabled


def test_saved_camera_is_restored_with_mode(tmp_path: Path) -> None:
    mode = CameraMode(1280, 720, Fraction(60000, 1001))
    config = QuickReplayConfig(input=CameraInputConfig("Camera 1", 1, "dshow", mode))
    session, bridge, _ = _session(tmp_path, config=config)
    asyncio.run(session.start())
    asyncio.run(_discover(session, bridge, (CameraInputDescriptor("Camera 1", 1),)))

    assert session.view_state().input_kind == CAMERA_KIND
    assert session.view_state().camera_backend == "dshow"
    built = session.build_input_config()
    assert built == CameraInputConfig("Camera 1", 1, "dshow", mode)


def test_unavailable_saved_input_disables_start(tmp_path: Path) -> None:
    config = QuickReplayConfig(input=NdiInputConfig("Missing"))
    session, bridge, _ = _session(tmp_path, config=config)
    asyncio.run(session.start())
    asyncio.run(_discover(session, bridge, (NdiInputDescriptor("Other"),)))

    state = session.view_state()
    assert state.selected_key is None
    assert not state.controls.start_enabled
    assert state.status_message == "Configured input is not currently available"


def test_new_camera_selection_has_no_mode(tmp_path: Path) -> None:
    session, bridge, _ = _session(tmp_path)
    asyncio.run(session.start())
    asyncio.run(_discover(session, bridge, (CameraInputDescriptor("Camera 1", 1),)))
    asyncio.run(session.set_input_kind(CAMERA_KIND))

    built = session.build_input_config()
    assert built == CameraInputConfig("Camera 1", 1, "any", None)


def test_backend_change_refreshes_camera_discovery(tmp_path: Path) -> None:
    session, bridge, _ = _session(tmp_path)
    asyncio.run(session.start())
    asyncio.run(session.set_input_kind(CAMERA_KIND))

    asyncio.run(session.set_camera_backend("dshow"))

    assert bridge.discovery_requests[-1] == "dshow"


def test_ndi_config_from_selection(tmp_path: Path) -> None:
    session, bridge, _ = _session(tmp_path)
    asyncio.run(session.start())
    asyncio.run(_discover(session, bridge, (NdiInputDescriptor("OBS"),)))

    assert session.build_input_config() == NdiInputConfig("OBS")


def test_successful_start_persists_input(tmp_path: Path) -> None:
    session, bridge, store = _session(tmp_path)
    asyncio.run(session.start())
    asyncio.run(_discover(session, bridge, (NdiInputDescriptor("OBS"),)))

    asyncio.run(session.start_recording())
    assert bridge.recording_configs == [NdiInputConfig("OBS")]

    bridge.events = [RecordingStarted(stream_info=_stream_info())]
    bridge.snapshot_value = ApplicationSnapshot(
        state=ApplicationState.RECORDING, stream_info=_stream_info()
    )
    asyncio.run(session.poll())

    assert store.load().input == NdiInputConfig("OBS")


def test_failed_start_does_not_persist(tmp_path: Path) -> None:
    session, bridge, store = _session(tmp_path)
    asyncio.run(session.start())
    asyncio.run(_discover(session, bridge, (NdiInputDescriptor("OBS"),)))

    asyncio.run(session.start_recording())
    # The worker reports an error instead of RecordingStarted.
    bridge.events = [ApplicationError(message="input open failed", source="worker")]
    bridge.snapshot_value = ApplicationSnapshot(
        state=ApplicationState.ERROR, error_message="input open failed"
    )
    asyncio.run(session.poll())

    assert not store.path.exists()


def test_config_save_failure_is_non_fatal(tmp_path: Path) -> None:
    store = _FailingStore(tmp_path / "config.json")
    session, bridge, _ = _session(tmp_path, store=store)
    asyncio.run(session.start())
    asyncio.run(_discover(session, bridge, (NdiInputDescriptor("OBS"),)))

    asyncio.run(session.start_recording())
    bridge.events = [RecordingStarted(stream_info=_stream_info())]
    bridge.snapshot_value = ApplicationSnapshot(
        state=ApplicationState.RECORDING, stream_info=_stream_info()
    )
    asyncio.run(session.poll())

    state = session.view_state()
    assert state.state == ApplicationState.RECORDING
    assert state.status_message is not None
    assert "could not be saved" in state.status_message


def test_view_state_formats_stream_and_metrics(tmp_path: Path) -> None:
    config = QuickReplayConfig(recording=RecordingConfig(buffer_duration_seconds=120))
    session, bridge, _ = _session(tmp_path, config=config)
    asyncio.run(session.start())
    bridge.snapshot_value = ApplicationSnapshot(
        state=ApplicationState.RECORDING,
        stream_info=_stream_info(),
        metrics=_metrics(),
    )
    asyncio.run(session.poll())

    state = session.view_state()
    assert state.stream_text == "1920 × 1080 | 60 fps | UYVY"
    assert state.audio_text == "Audio: 48 kHz / Stereo"
    assert state.metrics is not None
    assert state.metrics.buffer == "30.0 / 120 s"
    assert state.controls.replay_enabled


def test_view_state_without_metrics(tmp_path: Path) -> None:
    session, bridge, _ = _session(tmp_path)
    asyncio.run(session.start())
    bridge.snapshot_value = ApplicationSnapshot(state=ApplicationState.RECORDING)
    asyncio.run(session.poll())

    state = session.view_state()
    assert state.metrics is None
    assert state.stream_text == "—"


def test_resume_and_replay_actions(tmp_path: Path) -> None:
    session, bridge, _ = _session(tmp_path)
    asyncio.run(session.start())

    asyncio.run(session.request_replay())
    asyncio.run(session.resume_recording())

    assert bridge.replay_requests == 1
    assert bridge.resume_requests == 1


def test_shutdown_closes_bridge(tmp_path: Path) -> None:
    session, bridge, _ = _session(tmp_path)
    asyncio.run(session.start())

    asyncio.run(session.shutdown())

    assert bridge.shutdown_called
    assert bridge.closed


def test_saved_config_replaced_after_successful_start(tmp_path: Path) -> None:
    session, bridge, store = _session(tmp_path)
    asyncio.run(session.start())
    asyncio.run(_discover(session, bridge, (NdiInputDescriptor("OBS"),)))
    asyncio.run(session.start_recording())
    bridge.events = [RecordingStarted(stream_info=_stream_info())]
    bridge.snapshot_value = ApplicationSnapshot(state=ApplicationState.RECORDING)
    asyncio.run(session.poll())

    assert session.config.input == NdiInputConfig("OBS")
    assert store.load().input == NdiInputConfig("OBS")
    assert replace(session.config, input=NdiInputConfig("OBS")) == session.config
