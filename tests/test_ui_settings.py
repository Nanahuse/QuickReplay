"""Settings editor: draft conversion, validation, persistence and integration."""

import asyncio
from dataclasses import replace
from fractions import Fraction
from pathlib import Path

from fake_ui import FakeBridge

from quickreplay.app.state import ApplicationState
from quickreplay.application.events import InputsChanged
from quickreplay.application.models import ApplicationSnapshot
from quickreplay.configuration.errors import ConfigurationWriteError
from quickreplay.configuration.models import (
    QuickReplayConfig,
    RecordingConfig,
    ReplayConfig,
)
from quickreplay.configuration.store import ConfigurationStore
from quickreplay.input.models import (
    CameraInputConfig,
    CameraInputDescriptor,
    CameraMode,
    NdiInputConfig,
    NdiInputDescriptor,
)
from quickreplay.ui.session import CAMERA_KIND, UiSession
from quickreplay.ui.settings import (
    CAMERA_MODE_MESSAGE,
    RESTART_REQUIRED_MESSAGE,
    SettingsApplyResult,
    SettingsDraft,
    apply_message,
    build_settings_config,
    draft_from_config,
    restart_required,
)

CAMERA = CameraInputConfig("Camera 1", 1, "any", None)


class _FailingStore(ConfigurationStore):
    def save(self, config: QuickReplayConfig) -> None:
        raise ConfigurationWriteError("disk full")


class _CountingStore(ConfigurationStore):
    def __init__(self, path: Path) -> None:
        super().__init__(path)
        self.saves = 0

    def save(self, config: QuickReplayConfig) -> None:
        self.saves += 1
        super().save(config)


def _session(
    tmp_path: Path,
    *,
    config: QuickReplayConfig | None = None,
    store: ConfigurationStore | None = None,
) -> tuple[UiSession, FakeBridge]:
    bridge = FakeBridge()
    active_store = store or ConfigurationStore(tmp_path / "config.json")
    return UiSession(bridge, active_store, config or QuickReplayConfig()), bridge


async def _discover(session: UiSession, bridge: FakeBridge, inputs: tuple) -> None:
    bridge.events = [InputsChanged(request_id=bridge.next_discovery_id, inputs=inputs)]
    bridge.snapshot_value = ApplicationSnapshot(state=ApplicationState.IDLE)
    await session.poll()


def _camera_session(
    tmp_path: Path,
    *,
    config: QuickReplayConfig | None = None,
    store: ConfigurationStore | None = None,
) -> tuple[UiSession, FakeBridge]:
    session, bridge = _session(tmp_path, config=config, store=store)
    asyncio.run(session.start())
    asyncio.run(session.set_input_kind(CAMERA_KIND))
    asyncio.run(_discover(session, bridge, (CameraInputDescriptor("Camera 1", 1),)))
    return session, bridge


def _draft(config: QuickReplayConfig, camera_input: object) -> SettingsDraft:
    return draft_from_config(config, camera_input=camera_input)


# -- draft conversion ------------------------------------------------------


def test_camera_mode_to_draft() -> None:
    mode = CameraMode(1920, 1080, Fraction(60000, 1001))
    camera = replace(CAMERA, mode=mode)

    draft = _draft(QuickReplayConfig(), camera)

    assert draft.use_explicit_camera_mode is True
    assert draft.camera_width == "1920"
    assert draft.camera_height == "1080"
    assert draft.camera_fps_numerator == "60000"
    assert draft.camera_fps_denominator == "1001"
    assert draft.camera_available is True
    assert draft.camera_label == "Camera 1 (#1)"


def test_camera_mode_round_trip_60fps() -> None:
    mode = CameraMode(1920, 1080, Fraction(60, 1))
    camera = replace(CAMERA, mode=mode)

    draft = _draft(QuickReplayConfig(input=camera), camera)
    validation = build_settings_config(draft, QuickReplayConfig(input=camera), camera_input=camera)

    assert validation.errors == ()
    assert validation.config is not None
    assert validation.config.input == camera
    assert validation.config.input.mode == mode


def test_camera_mode_round_trip_5994fps() -> None:
    mode = CameraMode(1280, 720, Fraction(60000, 1001))
    camera = replace(CAMERA, mode=mode)
    config = QuickReplayConfig(input=camera)

    draft = _draft(config, camera)
    validation = build_settings_config(draft, config, camera_input=camera)

    assert validation.config is not None
    rebuilt = validation.config.input
    assert isinstance(rebuilt, CameraInputConfig)
    assert rebuilt.mode == mode
    assert rebuilt.mode is not None
    assert rebuilt.mode.fps == Fraction(60000, 1001)
    assert rebuilt.mode.fps.denominator == 1001


def test_automatic_mode_is_none() -> None:
    config = QuickReplayConfig(input=CAMERA)
    draft = _draft(config, CAMERA)
    assert draft.use_explicit_camera_mode is False
    assert draft.camera_width == ""

    draft = replace(draft, use_explicit_camera_mode=False)
    validation = build_settings_config(draft, config, camera_input=CAMERA)

    assert validation.config is not None
    assert validation.config.input == CAMERA
    assert validation.config.input.mode is None


def test_camera_mode_not_defaulted_when_absent() -> None:
    draft = _draft(QuickReplayConfig(input=CAMERA), CAMERA)
    # An explicit mode is never invented for a camera that has none.
    assert draft.use_explicit_camera_mode is False
    assert (draft.camera_width, draft.camera_height) == ("", "")
    assert (draft.camera_fps_numerator, draft.camera_fps_denominator) == ("", "")


def test_build_config_ignores_camera_section_without_camera_selection() -> None:
    config = QuickReplayConfig(input=NdiInputConfig("OBS"))
    draft = replace(
        _draft(config, None),
        use_explicit_camera_mode=True,
        camera_width="1920",
        camera_height="1080",
        camera_fps_numerator="60",
        camera_fps_denominator="1",
    )

    validation = build_settings_config(draft, config, camera_input=NdiInputConfig("OBS"))

    assert validation.errors == ()
    assert validation.config is not None
    assert validation.config.input == NdiInputConfig("OBS")


# -- validation ------------------------------------------------------------


def _errors(draft: SettingsDraft, *, camera_input: object = CAMERA) -> dict[str, str]:
    validation = build_settings_config(draft, QuickReplayConfig(), camera_input=camera_input)
    assert validation.config is None
    return {error.field: error.message for error in validation.errors}


def _explicit_draft(
    *,
    camera_width: str = "1920",
    camera_height: str = "1080",
    camera_fps_numerator: str = "60",
    camera_fps_denominator: str = "1",
    buffer_duration_seconds: str = "120",
    mpv_executable: str = "mpv",
) -> SettingsDraft:
    return SettingsDraft(
        use_explicit_camera_mode=True,
        camera_width=camera_width,
        camera_height=camera_height,
        camera_fps_numerator=camera_fps_numerator,
        camera_fps_denominator=camera_fps_denominator,
        buffer_duration_seconds=buffer_duration_seconds,
        mpv_executable=mpv_executable,
    )


def test_invalid_width_rejected() -> None:
    for value in ("", "0", "-1", "abc", "1920.0", "19 20", "1_0"):
        errors = _errors(_explicit_draft(camera_width=value))
        assert errors["camera_width"] == "Width must be a positive integer", value


def test_invalid_height_rejected() -> None:
    for value in ("", "0", "-5", "abc", "1080.0"):
        errors = _errors(_explicit_draft(camera_height=value))
        assert errors["camera_height"] == "Height must be a positive integer", value


def test_invalid_fps_numerator_rejected() -> None:
    for value in ("", "0", "-1", "abc", "59.94"):
        errors = _errors(_explicit_draft(camera_fps_numerator=value))
        assert errors["camera_fps_numerator"] == "FPS numerator must be a positive integer", value


def test_invalid_fps_denominator_rejected() -> None:
    for value in ("", "0", "-1", "abc", "1001.0"):
        errors = _errors(_explicit_draft(camera_fps_denominator=value))
        assert errors["camera_fps_denominator"] == "FPS denominator must be a positive integer", (
            value
        )


def test_buffer_duration_validation() -> None:
    for value in ("120", "1", " 90 "):
        validation = build_settings_config(
            _explicit_draft(buffer_duration_seconds=value), QuickReplayConfig(), camera_input=CAMERA
        )
        assert validation.config is not None, value

    for value in ("0", "-1", "", "120.0", "abc"):
        errors = _errors(_explicit_draft(buffer_duration_seconds=value))
        assert errors["buffer_duration_seconds"] == "Buffer duration must be a positive integer", (
            value
        )


def test_mpv_executable_validation() -> None:
    for value in ("mpv", r"C:\Tools\mpv\mpv.exe"):
        validation = build_settings_config(
            _explicit_draft(mpv_executable=value), QuickReplayConfig(), camera_input=CAMERA
        )
        assert validation.config is not None
        assert validation.config.replay.mpv_executable == value

    for value in ("", "   "):
        errors = _errors(_explicit_draft(mpv_executable=value))
        assert errors["mpv_executable"] == "mpv executable must not be empty"


def test_multiple_field_errors_are_all_reported() -> None:
    draft = replace(
        _explicit_draft(),
        camera_width="abc",
        buffer_duration_seconds="0",
        mpv_executable="",
    )
    errors = _errors(draft)
    assert set(errors) == {"camera_width", "buffer_duration_seconds", "mpv_executable"}


# -- session: cancel / apply / save failure --------------------------------


def test_draft_from_session_reflects_selected_camera(tmp_path: Path) -> None:
    session, _ = _camera_session(tmp_path)
    draft = session.settings_draft()
    assert draft.camera_available is True
    assert draft.camera_label == "Camera 1 (#1)"
    assert draft.buffer_duration_seconds == "120"
    assert draft.mpv_executable == "mpv"


def test_draft_for_ndi_disables_camera_section(tmp_path: Path) -> None:
    session, bridge = _session(tmp_path)
    asyncio.run(session.start())
    asyncio.run(_discover(session, bridge, (NdiInputDescriptor("OBS"),)))

    draft = session.settings_draft()
    assert draft.camera_available is False
    assert draft.camera_label == ""


def test_cancel_leaves_config_and_store_unchanged(tmp_path: Path) -> None:
    store = ConfigurationStore(tmp_path / "config.json")
    session, _ = _camera_session(tmp_path, store=store)
    before = session.config

    # Editing the draft without applying is equivalent to Cancel.
    draft = replace(session.settings_draft(), buffer_duration_seconds="90", mpv_executable="")
    assert draft.buffer_duration_seconds == "90"
    assert session.config == before
    assert not store.path.exists()


def test_apply_success_persists_and_updates_session(tmp_path: Path) -> None:
    store = ConfigurationStore(tmp_path / "config.json")
    session, _ = _camera_session(tmp_path, store=store)
    draft = replace(
        session.settings_draft(),
        use_explicit_camera_mode=True,
        camera_width="1920",
        camera_height="1080",
        camera_fps_numerator="60000",
        camera_fps_denominator="1001",
        buffer_duration_seconds="90",
    )

    result = asyncio.run(session.apply_settings(draft))

    assert result.ok
    assert result.restart_required
    expected_input = replace(CAMERA, mode=CameraMode(1920, 1080, Fraction(60000, 1001)))
    assert session.config.recording == RecordingConfig(90)
    assert session.config.input == expected_input
    assert store.load() == session.config


def test_apply_save_failure_keeps_old_config_and_file(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    initial = QuickReplayConfig(recording=RecordingConfig(120), replay=ReplayConfig("mpv"))
    ConfigurationStore(path).save(initial)
    session, _ = _camera_session(tmp_path, config=initial, store=_FailingStore(path))

    draft = replace(session.settings_draft(), buffer_duration_seconds="90")
    result = asyncio.run(session.apply_settings(draft))

    assert not result.ok
    assert "Could not save settings" in result.message
    assert session.config == initial
    assert ConfigurationStore(path).load() == initial
    # The draft the caller holds is not mutated by a failed apply.
    assert draft.buffer_duration_seconds == "90"


def test_apply_validation_failure_changes_nothing(tmp_path: Path) -> None:
    store = ConfigurationStore(tmp_path / "config.json")
    session, _ = _camera_session(tmp_path, store=store)
    before = session.config

    draft = replace(session.settings_draft(), buffer_duration_seconds="0", mpv_executable="")
    result = asyncio.run(session.apply_settings(draft))

    assert not result.ok
    assert {error.field for error in result.errors} == {
        "buffer_duration_seconds",
        "mpv_executable",
    }
    assert session.config == before
    assert not store.path.exists()


def test_apply_is_not_run_twice_concurrently(tmp_path: Path) -> None:
    store = _CountingStore(tmp_path / "config.json")
    session, _ = _camera_session(tmp_path, store=store)
    draft = replace(session.settings_draft(), buffer_duration_seconds="90")

    async def apply_twice() -> tuple[SettingsApplyResult, ...]:
        return await asyncio.gather(session.apply_settings(draft), session.apply_settings(draft))

    results = asyncio.run(apply_twice())

    assert store.saves == 1
    assert [result.ok for result in results].count(True) == 1


# -- restart-required and messages -----------------------------------------


def test_restart_required_flags() -> None:
    base = QuickReplayConfig()
    camera_off = replace(base, input=CAMERA)
    camera_on = replace(base, input=replace(CAMERA, mode=CameraMode(1920, 1080, Fraction(60, 1))))

    assert restart_required(base, replace(base, recording=RecordingConfig(90)))
    assert restart_required(base, replace(base, replay=ReplayConfig("other-mpv")))
    assert not restart_required(base, camera_off)
    assert not restart_required(camera_off, camera_on)
    assert not restart_required(camera_on, camera_off)


def test_apply_message_variants() -> None:
    assert apply_message(restart=False, input_changed=False) == "Settings saved."
    assert apply_message(restart=False, input_changed=True) == CAMERA_MODE_MESSAGE
    assert apply_message(restart=True, input_changed=True) == RESTART_REQUIRED_MESSAGE


def test_camera_only_apply_is_not_restart_required(tmp_path: Path) -> None:
    session, _ = _camera_session(tmp_path)
    draft = replace(
        session.settings_draft(),
        use_explicit_camera_mode=True,
        camera_width="1280",
        camera_height="720",
        camera_fps_numerator="60",
        camera_fps_denominator="1",
    )

    result = asyncio.run(session.apply_settings(draft))

    assert result.ok
    assert not result.restart_required
    assert result.message == CAMERA_MODE_MESSAGE
    assert session.view_state().status_message == CAMERA_MODE_MESSAGE


def test_buffer_apply_reports_restart_required(tmp_path: Path) -> None:
    session, _ = _camera_session(tmp_path)
    draft = replace(session.settings_draft(), buffer_duration_seconds="90")

    result = asyncio.run(session.apply_settings(draft))

    assert result.ok
    assert result.restart_required
    assert result.message == RESTART_REQUIRED_MESSAGE
    assert session.view_state().status_message == RESTART_REQUIRED_MESSAGE


# -- integration with input selection and recording ------------------------


def test_saved_camera_mode_used_by_build_input_config(tmp_path: Path) -> None:
    session, _ = _camera_session(tmp_path)
    draft = replace(
        session.settings_draft(),
        use_explicit_camera_mode=True,
        camera_width="1920",
        camera_height="1080",
        camera_fps_numerator="60000",
        camera_fps_denominator="1001",
    )
    asyncio.run(session.apply_settings(draft))

    built = session.build_input_config()

    assert built == replace(CAMERA, mode=CameraMode(1920, 1080, Fraction(60000, 1001)))


def test_saved_camera_mode_used_on_next_recording_start(tmp_path: Path) -> None:
    session, bridge = _camera_session(tmp_path)
    draft = replace(
        session.settings_draft(),
        use_explicit_camera_mode=True,
        camera_width="1920",
        camera_height="1080",
        camera_fps_numerator="30",
        camera_fps_denominator="1",
    )
    asyncio.run(session.apply_settings(draft))

    asyncio.run(session.start_recording())

    assert bridge.recording_configs == [
        CameraInputConfig(
            device_name="Camera 1",
            device_index=1,
            backend="any",
            mode=CameraMode(1920, 1080, Fraction(30, 1)),
        )
    ]


def test_ndi_selection_is_not_touched_by_settings(tmp_path: Path) -> None:
    config = QuickReplayConfig(input=NdiInputConfig("OBS"))
    session, bridge = _session(tmp_path, config=config)
    asyncio.run(session.start())
    asyncio.run(_discover(session, bridge, (NdiInputDescriptor("OBS"),)))
    draft = replace(session.settings_draft(), buffer_duration_seconds="90")

    result = asyncio.run(session.apply_settings(draft))

    assert result.ok
    assert session.config.input == NdiInputConfig("OBS")
    assert session.build_input_config() == NdiInputConfig("OBS")
    asyncio.run(session.start_recording())
    assert bridge.recording_configs == [NdiInputConfig("OBS")]


def test_camera_mode_change_does_not_restart_recording(tmp_path: Path) -> None:
    session, bridge = _camera_session(tmp_path)
    bridge.snapshot_value = ApplicationSnapshot(state=ApplicationState.RECORDING)
    asyncio.run(session.poll())
    draft = replace(
        session.settings_draft(),
        use_explicit_camera_mode=True,
        camera_width="1280",
        camera_height="720",
        camera_fps_numerator="60",
        camera_fps_denominator="1",
    )

    result = asyncio.run(session.apply_settings(draft))

    assert result.ok
    assert session.view_state().state == ApplicationState.RECORDING
    assert bridge.recording_configs == []
