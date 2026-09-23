"""Configuration JSON codec: strict validation and round trips."""

import pytest

from quickreplay.configuration.codec import (
    config_from_json_object,
    config_to_json_object,
)
from quickreplay.configuration.errors import (
    ConfigurationValidationError,
    UnsupportedConfigVersionError,
)
from quickreplay.configuration.models import (
    QuickReplayConfig,
    RecordingConfig,
    ReplayConfig,
)
from quickreplay.input.models import NdiInputConfig


def test_default_round_trip() -> None:
    config = QuickReplayConfig()
    restored = config_from_json_object(config_to_json_object(config))
    assert restored == config


def test_canonical_json_object() -> None:
    obj = config_to_json_object(QuickReplayConfig())
    assert list(obj) == ["schema_version", "input", "recording", "replay", "ui"]
    assert obj == {
        "schema_version": 1,
        "input": None,
        "recording": {"buffer_duration_seconds": 120},
        "replay": {"mpv_executable": "mpv"},
        "ui": {},
    }


def test_ndi_round_trip() -> None:
    config = QuickReplayConfig(input=NdiInputConfig("OBS"))
    restored = config_from_json_object(config_to_json_object(config))
    assert restored.input == NdiInputConfig("OBS")


def test_unicode_ndi_round_trip() -> None:
    source = "配信用PC (NDI ソース)"
    config = QuickReplayConfig(input=NdiInputConfig(source))
    obj = config_to_json_object(config)
    assert obj["input"] == {"type": "ndi", "source_name": source}
    assert config_from_json_object(obj).input == NdiInputConfig(source)


def test_missing_sections_use_defaults() -> None:
    restored = config_from_json_object({"schema_version": 1})
    assert restored == QuickReplayConfig()


def test_unknown_input_type_is_rejected() -> None:
    with pytest.raises(ConfigurationValidationError):
        config_from_json_object({"schema_version": 1, "input": {"type": "foo"}})


def test_camera_input_type_is_unsupported() -> None:
    with pytest.raises(ConfigurationValidationError, match="input.type 'camera' is not supported"):
        config_from_json_object({"schema_version": 1, "input": {"type": "camera"}})


@pytest.mark.parametrize(
    "value",
    [
        {"schema_version": 1, "extra": 1},
        {"schema_version": 1, "recording": {"buffer_duration_seconds": 120, "x": 1}},
        {"schema_version": 1, "replay": {"mpv_executable": "mpv", "x": 1}},
        {"schema_version": 1, "ui": {"x": 1}},
        {"schema_version": 1, "input": {"type": "ndi", "source_name": "x", "y": 1}},
    ],
)
def test_unknown_fields_are_rejected(value: object) -> None:
    with pytest.raises(ConfigurationValidationError):
        config_from_json_object(value)


@pytest.mark.parametrize("version", [0, 2, 999, "1", True, None, 1.0])
def test_invalid_schema_version_is_rejected(version: object) -> None:
    with pytest.raises((UnsupportedConfigVersionError, ConfigurationValidationError)):
        config_from_json_object({"schema_version": version})


def test_missing_schema_version_is_rejected() -> None:
    with pytest.raises(ConfigurationValidationError):
        config_from_json_object({})


@pytest.mark.parametrize(
    "value",
    [
        {"schema_version": 1, "recording": {"buffer_duration_seconds": True}},
        {"schema_version": 1, "recording": {"buffer_duration_seconds": "120"}},
        {"schema_version": 1, "recording": {"buffer_duration_seconds": 0}},
        {"schema_version": 1, "recording": {"buffer_duration_seconds": -5}},
        {"schema_version": 1, "replay": {"mpv_executable": ""}},
        {"schema_version": 1, "replay": {"mpv_executable": 5}},
        {"schema_version": 1, "input": {"type": "ndi", "source_name": ""}},
        {"schema_version": 1, "input": {"type": "ndi", "source_name": 5}},
    ],
)
def test_wrong_types_and_values_are_rejected(value: object) -> None:
    with pytest.raises(ConfigurationValidationError):
        config_from_json_object(value)


def test_validation_error_includes_field_path() -> None:
    with pytest.raises(ConfigurationValidationError) as info:
        config_from_json_object(
            {"schema_version": 1, "recording": {"buffer_duration_seconds": True}}
        )
    assert "recording.buffer_duration_seconds" in str(info.value)


def test_recording_and_replay_defaults_can_be_overridden() -> None:
    config = QuickReplayConfig(
        recording=RecordingConfig(buffer_duration_seconds=300),
        replay=ReplayConfig(mpv_executable="C:\\Tools\\mpv\\mpv.exe"),
    )
    restored = config_from_json_object(config_to_json_object(config))
    assert restored == config
