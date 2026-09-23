"""JSON object <-> typed configuration conversion.

The codec is pure: it performs strict type validation, rejects unknown fields
and builds the existing domain models (whose own validation runs too).  It does
no file I/O.
"""

from collections.abc import Callable
from typing import Any, TypeVar

from quickreplay.configuration.errors import (
    ConfigurationValidationError,
    UnsupportedConfigVersionError,
)
from quickreplay.configuration.models import (
    CURRENT_SCHEMA_VERSION,
    QuickReplayConfig,
    RecordingConfig,
    ReplayConfig,
    UiConfig,
)
from quickreplay.input.models import InputConfig, NdiInputConfig

_T = TypeVar("_T")

_TOP_LEVEL_FIELDS = {"schema_version", "input", "recording", "replay", "ui"}
_NDI_FIELDS = {"type", "source_name"}
_RECORDING_FIELDS = {"buffer_duration_seconds"}
_REPLAY_FIELDS = {"mpv_executable"}


def config_from_json_object(value: object) -> QuickReplayConfig:
    """Parse a JSON object into a validated :class:`QuickReplayConfig`."""
    obj = _require_object(value, "config")
    if "schema_version" not in obj:
        raise ConfigurationValidationError("schema_version is required")
    version = _require_int(obj["schema_version"], "schema_version")
    if version != CURRENT_SCHEMA_VERSION:
        raise UnsupportedConfigVersionError(
            f"unsupported schema_version {version}; expected {CURRENT_SCHEMA_VERSION}"
        )
    _reject_unknown(obj, _TOP_LEVEL_FIELDS, "")

    input_config = _parse_input(obj["input"]) if "input" in obj else None
    recording = _parse_recording(obj.get("recording", {}))
    replay = _parse_replay(obj.get("replay", {}))
    ui = _parse_ui(obj.get("ui", {}))
    return QuickReplayConfig(
        schema_version=version,
        input=input_config,
        recording=recording,
        replay=replay,
        ui=ui,
    )


def config_to_json_object(config: QuickReplayConfig) -> dict[str, object]:
    """Serialize a configuration into its canonical JSON object."""
    return {
        "schema_version": config.schema_version,
        "input": _input_to_json_object(config.input),
        "recording": {"buffer_duration_seconds": config.recording.buffer_duration_seconds},
        "replay": {"mpv_executable": config.replay.mpv_executable},
        "ui": {},
    }


# -- parsing ---------------------------------------------------------------
def _parse_input(value: object) -> InputConfig | None:
    if value is None:
        return None
    obj = _require_object(value, "input")
    kind = _require_str(_required(obj, "type", "input"), "input.type")
    if kind == "ndi":
        _reject_unknown(obj, _NDI_FIELDS, "input")
        source_name = _require_str(_required(obj, "source_name", "input"), "input.source_name")
        return _domain(lambda: NdiInputConfig(source_name), "input")
    raise ConfigurationValidationError(f"input.type {kind!r} is not supported")


def _parse_recording(value: object) -> RecordingConfig:
    obj = _require_object(value, "recording")
    _reject_unknown(obj, _RECORDING_FIELDS, "recording")
    seconds = _require_int(
        obj.get("buffer_duration_seconds", RecordingConfig().buffer_duration_seconds),
        "recording.buffer_duration_seconds",
    )
    return RecordingConfig(seconds)


def _parse_replay(value: object) -> ReplayConfig:
    obj = _require_object(value, "replay")
    _reject_unknown(obj, _REPLAY_FIELDS, "replay")
    executable = _require_str(
        obj.get("mpv_executable", ReplayConfig().mpv_executable), "replay.mpv_executable"
    )
    return ReplayConfig(executable)


def _parse_ui(value: object) -> UiConfig:
    obj = _require_object(value, "ui")
    _reject_unknown(obj, set(), "ui")
    return UiConfig()


# -- serialization ---------------------------------------------------------
def _input_to_json_object(input_config: InputConfig | None) -> dict[str, object] | None:
    if input_config is None:
        return None
    if isinstance(input_config, NdiInputConfig):
        return {"type": "ndi", "source_name": input_config.source_name}
    raise TypeError(f"unsupported input configuration: {input_config!r}")


# -- helpers ---------------------------------------------------------------
def _required(obj: dict[str, Any], key: str, path: str) -> object:
    if key not in obj:
        raise ConfigurationValidationError(f"{_path(path, key)} is required")
    return obj[key]


def _path(parent: str, key: str) -> str:
    return f"{parent}.{key}" if parent else key


def _require_object(value: object, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ConfigurationValidationError(f"{path} must be an object")
    return value


def _require_str(value: object, path: str) -> str:
    if not isinstance(value, str):
        raise ConfigurationValidationError(f"{path} must be a string")
    return value


def _require_int(value: object, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigurationValidationError(f"{path} must be an integer")
    return value


def _reject_unknown(mapping: dict[str, Any], allowed: set[str], path: str) -> None:
    for key in mapping:
        if key not in allowed:
            raise ConfigurationValidationError(f"unknown field {key!r} in {path or 'config'}")


def _domain[T](builder: Callable[[], T], path: str) -> T:
    try:
        return builder()
    except ValueError as exc:
        raise ConfigurationValidationError(f"{path}: {exc}") from exc
