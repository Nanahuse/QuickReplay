"""ConfigurationStore: load defaults, parse errors, atomic save and Unicode."""

import dataclasses
import os
from pathlib import Path

import pytest

from quickreplay.configuration.errors import (
    ConfigurationParseError,
    ConfigurationReadError,
    ConfigurationWriteError,
)
from quickreplay.configuration.models import QuickReplayConfig, ReplayConfig
from quickreplay.configuration.store import ConfigurationStore
from quickreplay.input.models import NdiInputConfig


def test_missing_file_returns_defaults_without_creating_it(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    store = ConfigurationStore(path)

    config = store.load()

    assert config == QuickReplayConfig()
    assert not path.exists()


def test_minimal_file_uses_default_sections(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text('{"schema_version": 1}', encoding="utf-8")

    config = ConfigurationStore(path).load()

    assert config == QuickReplayConfig()


def test_malformed_json_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text('{"schema_version": 1,', encoding="utf-8")

    with pytest.raises(ConfigurationParseError):
        ConfigurationStore(path).load()


def test_read_error_is_wrapped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "config.json"
    path.write_text('{"schema_version": 1}', encoding="utf-8")

    def boom(self: Path, *args, **kwargs) -> str:
        raise OSError("permission denied")

    monkeypatch.setattr(Path, "read_text", boom)
    with pytest.raises(ConfigurationReadError):
        ConfigurationStore(path).load()


def test_save_and_load_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    store = ConfigurationStore(path)
    config = QuickReplayConfig(input=NdiInputConfig("OBS"))

    store.save(config)

    assert store.load() == config


def test_save_is_canonical_utf8(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    store = ConfigurationStore(path)
    store.save(QuickReplayConfig(input=NdiInputConfig("配信用PC")))

    text = path.read_text(encoding="utf-8")
    assert text.endswith("\n")
    assert '\n  "schema_version": 1,' in text
    assert "配信用PC" in text  # ensure_ascii=False
    assert "\\u" not in text
    assert not (tmp_path / "config.json.tmp").exists()


def test_save_creates_parent_directories(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "dir" / "config.json"
    store = ConfigurationStore(path)

    store.save(QuickReplayConfig())

    assert path.exists()


def test_save_over_existing_file(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    store = ConfigurationStore(path)
    store.save(QuickReplayConfig(input=NdiInputConfig("first")))
    store.save(QuickReplayConfig(input=NdiInputConfig("second")))

    assert store.load().input == NdiInputConfig("second")
    assert not (tmp_path / "config.json.tmp").exists()


def test_atomic_save_failure_preserves_existing_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "config.json"
    store = ConfigurationStore(path)
    store.save(QuickReplayConfig(input=NdiInputConfig("original")))
    original = path.read_text(encoding="utf-8")

    def boom(src, dst) -> None:
        raise OSError("replace failed")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(ConfigurationWriteError):
        store.save(QuickReplayConfig(input=NdiInputConfig("new")))

    assert path.read_text(encoding="utf-8") == original
    assert store.load().input == NdiInputConfig("original")
    assert not (tmp_path / "config.json.tmp").exists()


def test_write_error_is_wrapped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "config.json"

    def boom(fd: int) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(os, "fsync", boom)

    with pytest.raises(ConfigurationWriteError):
        ConfigurationStore(path).save(QuickReplayConfig())

    assert not (tmp_path / "config.json.tmp").exists()


def test_unicode_filesystem_path(tmp_path: Path) -> None:
    path = tmp_path / "設定" / "クイックリプレイ" / "config.json"
    store = ConfigurationStore(path)

    store.save(QuickReplayConfig(input=NdiInputConfig("配信")))

    assert store.load().input == NdiInputConfig("配信")


def test_windows_mpv_path_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    store = ConfigurationStore(path)
    config = dataclasses.replace(
        QuickReplayConfig(),
        replay=ReplayConfig(mpv_executable="C:\\Users\\名前\\Apps\\mpv\\mpv.exe"),
    )

    store.save(config)

    assert store.load().replay.mpv_executable == "C:\\Users\\名前\\Apps\\mpv\\mpv.exe"
