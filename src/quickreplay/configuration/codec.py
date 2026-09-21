"""JSON object <-> typed configuration conversion.

The codec is pure: it performs strict type validation, rejects unknown fields
and builds the existing domain models (whose own validation runs too).  It does
no file I/O.
"""

from collections.abc import Callable
from fractions import Fraction
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
from quickreplay.input.models import (
    CameraInputConfig,
    CameraMode,
    InputConfig,
    NdiInputConfig,
)

_T = TypeVar("_T")

_TOP_LEVEL_FIELDS = {"schema_version", "input", "recording", "replay", "ui"}
_CAMERA_FIELDS = {"type", "device_name", "device_index", "backend", "mode"}
_NDI_FIELDS = {"type", "source_name"}
_MODE_FIELDS = {"width", "height", "fps"}
_FRACTION_FIELDS = {"numerator", "denominator"}
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
    if kind == "camera":
        _reject_unknown(obj, _CAMERA_FIELDS, "input")
        device_name = _require_str(_required(obj, "device_name", "input"), "input.device_name")
        device_index = _require_int(_required(obj, "device_index", "input"), "input.device_index")
        backend = _require_str(_required(obj, "backend", "input"), "input.backend")
        mode = _parse_mode(obj["mode"]) if "mode" in obj else None
        return _domain(lambda: CameraInputConfig(device_name, device_index, backend, mode), "input")
    raise ConfigurationValidationError(f"input.type {kind!r} is not supported")


def _parse_mode(value: object) -> CameraMode | None:
    if value is None:
        return None
    obj = _require_object(value, "input.mode")
    _reject_unknown(obj, _MODE_FIELDS, "input.mode")
    width = _require_int(_required(obj, "width", "input.mode"), "input.mode.width")
    height = _require_int(_required(obj, "height", "input.mode"), "input.mode.height")
    fps = _parse_fraction(_required(obj, "fps", "input.mode"), "input.mode.fps")
    return _domain(lambda: CameraMode(width, height, fps), "input.mode")


def _parse_fraction(value: object, path: str) -> Fraction:
    obj = _require_object(value, path)
    _reject_unknown(obj, _FRACTION_FIELDS, path)
    numerator = _require_int(_required(obj, "numerator", path), f"{path}.numerator")
    denominator = _require_int(_required(obj, "denominator", path), f"{path}.denominator")
    if numerator <= 0:
        raise ConfigurationValidationError(f"{path}.numerator must be a positive integer")
    if denominator <= 0:
        raise ConfigurationValidationError(f"{path}.denominator must be a positive integer")
    return Fraction(numerator, denominator)


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
    return {
        "type": "camera",
        "device_name": input_config.device_name,
        "device_index": input_config.device_index,
        "backend": input_config.backend,
        "mode": _mode_to_json_object(input_config.mode),
    }


def _mode_to_json_object(mode: CameraMode | None) -> dict[str, object] | None:
    if mode is None:
        return None
    return {
        "width": mode.width,
        "height": mode.height,
        "fps": {
            "numerator": mode.fps.numerator,
            "denominator": mode.fps.denominator,
        },
    }


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
