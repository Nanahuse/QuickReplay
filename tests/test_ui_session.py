"""UiSession: discovery correlation, selection, persistence and view state."""

import asyncio
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
    NdiInputConfig,
    NdiInputDescriptor,
    StreamInfo,
    VideoStreamInfo,
)
from quickreplay.recording.models import RecordingMetrics
from quickreplay.replay.errors import MpvProcessExitedError
from quickreplay.replay.models import ReplayAsset, SetPoint
from quickreplay.ui.session import UiSession

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


class _BlockingReplayBridge(FakeBridge):
    def __init__(self) -> None:
        super().__init__()
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def step_forward(self) -> None:
        self.entered.set()
        await self.release.wait()
        await super().step_forward()


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
    assert bridge.discovery_requests == ["ndi"]


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


def test_unavailable_saved_input_disables_start(tmp_path: Path) -> None:
    config = QuickReplayConfig(input=NdiInputConfig("Missing"))
    session, bridge, _ = _session(tmp_path, config=config)
    asyncio.run(session.start())
    asyncio.run(_discover(session, bridge, (NdiInputDescriptor("Other"),)))

    state = session.view_state()
    assert state.selected_key is None
    assert not state.controls.start_enabled
    assert state.status_message == "Configured input is not currently available"


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


def test_shutdown_closes_bridge(tmp_path: Path) -> None:
    session, bridge, _ = _session(tmp_path)
    asyncio.run(session.start())

    asyncio.run(session.shutdown())

    assert bridge.shutdown_called
    assert bridge.closed


def _asset(duration_ns: int = 12_000_000_000, fps: Fraction = FPS) -> ReplayAsset:
    return ReplayAsset(Path("replay.mkv"), duration_ns, fps)


async def _enter_replay(session, bridge, *, duration_ns: int = 12_000_000_000) -> None:
    bridge.snapshot_value = ApplicationSnapshot(
        state=ApplicationState.REPLAY, replay_asset=_asset(duration_ns)
    )
    await session.poll()


def test_replay_entry_populates_view(tmp_path: Path) -> None:
    session, bridge, _ = _session(tmp_path)
    asyncio.run(session.start())
    bridge.position_value = 3_250_000_000
    bridge.paused_value = True

    asyncio.run(_enter_replay(session, bridge))

    view = session.view_state().replay
    assert view is not None
    assert view.position_ns == 3_250_000_000
    assert view.duration_ns == 12_000_000_000
    assert view.paused is True
    assert view.position_text == "00:03.250"
    assert view.duration_text == "00:12.000"
    assert view.set_point_text == "—"
    assert view.time_difference_text == "—"
    assert view.frame_difference_text == "—"
    assert view.has_set_point is False


def test_replay_exit_clears_state(tmp_path: Path) -> None:
    session, bridge, _ = _session(tmp_path)
    asyncio.run(session.start())
    asyncio.run(_enter_replay(session, bridge))
    bridge.set_point_value = 2_000_000_000
    asyncio.run(session.set_replay_point())
    assert session.view_state().replay is not None

    bridge.snapshot_value = ApplicationSnapshot(state=ApplicationState.RESUMING)
    asyncio.run(session.poll())
    assert session.view_state().replay is None

    # A new replay must not carry over the previous set point.
    asyncio.run(_enter_replay(session, bridge))
    view = session.view_state().replay
    assert view is not None
    assert view.has_set_point is False
    assert view.set_point_text == "—"


def test_toggle_play_uses_core_pause_state(tmp_path: Path) -> None:
    session, bridge, _ = _session(tmp_path)
    asyncio.run(session.start())
    asyncio.run(_enter_replay(session, bridge))

    bridge.paused_value = True
    asyncio.run(session.toggle_play_pause())
    assert bridge.play_calls == 1
    assert bridge.pause_calls == 0

    bridge.paused_value = False
    asyncio.run(session.toggle_play_pause())
    assert bridge.pause_calls == 1


def test_replay_action_pending_blocks_only_overlapping_action(tmp_path: Path) -> None:
    async def scenario() -> None:
        bridge = _BlockingReplayBridge()
        session, _, _ = _session(tmp_path, bridge=bridge)
        first = asyncio.create_task(session.step_forward())
        await bridge.entered.wait()

        await session.step_forward()
        assert bridge.step_forward_calls == 0

        bridge.release.set()
        await first
        await session.step_forward()
        assert bridge.step_forward_calls == 2

    asyncio.run(scenario())


def test_set_point_uses_bridge_value_and_shows_differences(tmp_path: Path) -> None:
    session, bridge, _ = _session(tmp_path)
    asyncio.run(session.start())
    asyncio.run(_enter_replay(session, bridge))
    bridge.position_value = 3_250_000_000
    bridge.set_point_value = 2_500_000_000
    bridge.time_difference_value = 750_000_000
    bridge.frame_difference_value = 45

    asyncio.run(session.set_replay_point())

    view = session.view_state().replay
    assert view is not None
    assert view.has_set_point is True
    assert view.set_point_text == "00:02.500"
    assert view.time_difference_text == "+00:00.750"
    assert view.frame_difference_text == "+45"
    assert bridge.set_point_calls == 1
    assert bridge.time_difference_points == [SetPoint(2_500_000_000)]
    assert bridge.frame_difference_points == [SetPoint(2_500_000_000)]


def test_differences_are_not_queried_without_set_point(tmp_path: Path) -> None:
    session, bridge, _ = _session(tmp_path)
    asyncio.run(session.start())
    asyncio.run(_enter_replay(session, bridge))

    assert bridge.time_difference_points == []
    assert bridge.frame_difference_points == []


def test_non_replay_poll_does_not_query_replay_api(tmp_path: Path) -> None:
    session, bridge, _ = _session(tmp_path)
    asyncio.run(session.start())
    bridge.snapshot_value = ApplicationSnapshot(state=ApplicationState.RECORDING)

    asyncio.run(session.poll())

    assert bridge.position_calls == 0
    assert bridge.is_paused_calls == 0


def test_replay_status_refreshes_during_replay(tmp_path: Path) -> None:
    session, bridge, _ = _session(tmp_path)
    asyncio.run(session.start())
    asyncio.run(_enter_replay(session, bridge))
    bridge.set_point_value = 2_000_000_000
    asyncio.run(session.set_replay_point())
    bridge.position_value = 2_050_000_000
    bridge.time_difference_value = 50_000_000
    bridge.frame_difference_value = 3

    asyncio.run(session.poll())

    view = session.view_state().replay
    assert view is not None
    assert view.position_ns == 2_050_000_000
    assert view.time_difference_text == "+00:00.050"
    assert view.frame_difference_text == "+3"


def test_negative_frame_difference_is_signed(tmp_path: Path) -> None:
    session, bridge, _ = _session(tmp_path)
    asyncio.run(session.start())
    asyncio.run(_enter_replay(session, bridge))
    bridge.set_point_value = 2_000_000_000
    bridge.frame_difference_value = -12
    bridge.time_difference_value = -750_000_000

    asyncio.run(session.set_replay_point())

    view = session.view_state().replay
    assert view is not None
    assert view.frame_difference_text == "-12"
    assert view.time_difference_text == "-00:00.750"


def test_mpv_exit_during_status_refresh_is_not_an_error(tmp_path: Path) -> None:
    session, bridge, _ = _session(tmp_path)
    asyncio.run(session.start())
    asyncio.run(_enter_replay(session, bridge))

    bridge.position_error = MpvProcessExitedError("mpv exited")
    asyncio.run(session.poll())
    assert session.view_state().error_message is None

    bridge.position_error = None
    bridge.snapshot_value = ApplicationSnapshot(state=ApplicationState.RESUMING)
    asyncio.run(session.poll())
    assert session.view_state().replay is None


def test_transient_replay_error_is_reported(tmp_path: Path) -> None:
    session, bridge, _ = _session(tmp_path)
    asyncio.run(session.start())
    asyncio.run(_enter_replay(session, bridge))

    bridge.position_error = RuntimeError("seek failed")
    asyncio.run(session.poll())

    assert "Replay control failed" in (session.view_state().error_message or "")
    # The application state machine is unchanged.
    assert session.view_state().state == ApplicationState.REPLAY

    bridge.position_error = None
    bridge.snapshot_value = ApplicationSnapshot(state=ApplicationState.RESUMING)
    asyncio.run(session.poll())

    assert session.view_state().error_message is None
