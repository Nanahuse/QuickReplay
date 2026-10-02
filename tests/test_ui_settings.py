"""Settings draft validation and UiSession persistence behavior."""

import asyncio
from pathlib import Path

import pytest
from fake_ui import FakeBridge

from quickreplay.configuration.errors import ConfigurationWriteError
from quickreplay.configuration.models import QuickReplayConfig
from quickreplay.configuration.store import ConfigurationStore
from quickreplay.input.models import NdiInputConfig
from quickreplay.ui.session import UiSession
from quickreplay.ui.settings import (
    RESTART_REQUIRED_MESSAGE,
    SETTINGS_SAVED_MESSAGE,
    SettingsDraft,
    apply_message,
    build_settings_config,
    draft_from_config,
    restart_required,
)


class _FailingStore(ConfigurationStore):
    def save(self, config: QuickReplayConfig) -> None:
        raise ConfigurationWriteError("disk full")


def test_draft_uses_persisted_runtime_settings() -> None:
    config = QuickReplayConfig(input=NdiInputConfig("Studio"))
    draft = draft_from_config(config)
    assert draft.buffer_duration_seconds == "120"
    assert draft.mpv_executable == "mpv"


def test_apply_config_preserves_input_selection() -> None:
    config = QuickReplayConfig(input=NdiInputConfig("Studio"))
    result = build_settings_config(SettingsDraft("60", "mpv.exe"), config)
    assert result.errors == ()
    assert result.config is not None
    assert result.config.input == NdiInputConfig("Studio")
    assert result.config.recording.buffer_duration_seconds == 60
    assert result.config.replay.mpv_executable == "mpv.exe"


@pytest.mark.parametrize(
    ("draft", "field"),
    [
        (SettingsDraft("0", "mpv"), "buffer_duration_seconds"),
        (SettingsDraft("abc", "mpv"), "buffer_duration_seconds"),
        (SettingsDraft("60", ""), "mpv_executable"),
    ],
)
def test_invalid_draft_returns_field_errors(draft: SettingsDraft, field: str) -> None:
    result = build_settings_config(draft, QuickReplayConfig())
    assert result.config is None
    assert field in {error.field for error in result.errors}


def test_restart_required_only_tracks_runtime_settings() -> None:
    current = QuickReplayConfig(input=NdiInputConfig("A"))
    other_input = QuickReplayConfig(input=NdiInputConfig("B"))
    candidate = build_settings_config(SettingsDraft("120", "mpv"), other_input).config
    assert candidate is not None
    assert not restart_required(current, candidate)
    changed = build_settings_config(SettingsDraft("60", "mpv"), current).config
    assert changed is not None
    assert restart_required(current, changed)


def test_apply_message_reflects_restart_requirement() -> None:
    assert apply_message(restart=False) == SETTINGS_SAVED_MESSAGE
    assert apply_message(restart=True) == RESTART_REQUIRED_MESSAGE


def test_session_apply_persists_settings_without_changing_input(tmp_path: Path) -> None:
    initial = QuickReplayConfig(input=NdiInputConfig("Studio"))
    store = ConfigurationStore(tmp_path / "config.json")
    session = UiSession(FakeBridge(), store, initial)
    result = asyncio.run(session.apply_settings(SettingsDraft("60", "mpv.exe")))
    assert result.ok and result.restart_required
    assert session.config.input == NdiInputConfig("Studio")
    assert store.load() == session.config


def test_failed_save_does_not_replace_session_config(tmp_path: Path) -> None:
    initial = QuickReplayConfig(input=NdiInputConfig("Studio"))
    session = UiSession(FakeBridge(), _FailingStore(tmp_path / "config.json"), initial)
    result = asyncio.run(session.apply_settings(SettingsDraft("60", "mpv.exe")))
    assert not result.ok
    assert "Could not save settings" in result.message
    assert session.config == initial
