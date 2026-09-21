"""Configuration to runtime settings conversion."""

import dataclasses
from pathlib import Path

from quickreplay.application.controller import ApplicationController
from quickreplay.configuration.codec import config_to_json_object
from quickreplay.configuration.models import QuickReplayConfig, RecordingConfig, ReplayConfig
from quickreplay.configuration.runtime import build_application_settings
from quickreplay.replay.controller import ReplayControllerSettings
from quickreplay.worker.settings import RecorderWorkerSettings


def test_buffer_duration_is_converted_to_nanoseconds(tmp_path: Path) -> None:
    config = QuickReplayConfig(recording=RecordingConfig(buffer_duration_seconds=120))

    settings = build_application_settings(config, working_directory=tmp_path)

    assert settings.worker is not None
    assert settings.worker.buffer_duration_ns == 120_000_000_000


def test_internal_worker_defaults_are_preserved(tmp_path: Path) -> None:
    config = QuickReplayConfig(recording=RecordingConfig(buffer_duration_seconds=300))

    settings = build_application_settings(config, working_directory=tmp_path)

    assert settings.worker is not None
    defaults = RecorderWorkerSettings(working_directory=tmp_path)
    assert settings.worker.segment_duration_ns == defaults.segment_duration_ns
    assert settings.worker.video_queue_capacity == defaults.video_queue_capacity
    assert settings.worker.audio_queue_capacity == defaults.audio_queue_capacity
    assert settings.worker.av_reorder_holdback_ns == defaults.av_reorder_holdback_ns
    assert settings.worker.working_directory == tmp_path


def test_mpv_executable_is_converted(tmp_path: Path) -> None:
    config = QuickReplayConfig(replay=ReplayConfig(mpv_executable="C:\\Tools\\mpv\\mpv.exe"))

    settings = build_application_settings(config, working_directory=tmp_path)

    assert settings.replay.mpv_executable == "C:\\Tools\\mpv\\mpv.exe"
    defaults = ReplayControllerSettings()
    assert settings.replay.startup_timeout_seconds == defaults.startup_timeout_seconds
    assert settings.replay.command_timeout_seconds == defaults.command_timeout_seconds
    assert settings.replay.shutdown_timeout_seconds == defaults.shutdown_timeout_seconds


def test_application_settings_have_worker_and_replay(tmp_path: Path) -> None:
    config = QuickReplayConfig()

    settings = build_application_settings(config, working_directory=tmp_path)

    assert settings.worker is not None
    assert settings.replay is not None


def test_working_directory_is_not_persisted() -> None:
    obj = config_to_json_object(QuickReplayConfig())
    assert "working_directory" not in str(obj)


def test_seconds_to_ns_uses_integer_math(tmp_path: Path) -> None:
    config = QuickReplayConfig(recording=RecordingConfig(buffer_duration_seconds=7))

    settings = build_application_settings(config, working_directory=tmp_path)

    assert settings.worker is not None
    assert settings.worker.buffer_duration_ns == 7_000_000_000
    assert isinstance(settings.worker.buffer_duration_ns, int)


def test_application_controller_can_be_constructed(tmp_path: Path) -> None:
    config = dataclasses.replace(
        QuickReplayConfig(),
        replay=ReplayConfig(mpv_executable="mpv"),
    )
    settings = build_application_settings(config, working_directory=tmp_path)

    controller = ApplicationController(settings)

    # The configuration only feeds settings; no worker is started here.
    assert controller.state.value == "starting"
    assert settings.worker is not None
    assert settings.worker.buffer_duration_ns == 120_000_000_000
