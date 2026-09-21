"""Configuration to runtime settings conversion."""

from pathlib import Path

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


def test_working_directory_is_not_persisted() -> None:
    obj = config_to_json_object(QuickReplayConfig())
    assert "working_directory" not in str(obj)
