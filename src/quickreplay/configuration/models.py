"""Immutable persisted configuration models.

These models describe the stable user-facing configuration.  Internal runtime
tuning (queue capacities, timeouts, hold-back windows, ...) is deliberately not
part of them; it lives in the runtime settings models instead.
"""

from dataclasses import dataclass, field

from quickreplay.configuration.errors import (
    ConfigurationValidationError,
    UnsupportedConfigVersionError,
)
from quickreplay.input.models import InputConfig

CURRENT_SCHEMA_VERSION = 1
"""The configuration schema version written by this application."""


@dataclass(frozen=True, slots=True)
class RecordingConfig:
    """Persisted recording settings."""

    buffer_duration_seconds: int = 120

    def __post_init__(self) -> None:
        if isinstance(self.buffer_duration_seconds, bool) or not isinstance(
            self.buffer_duration_seconds, int
        ):
            raise ConfigurationValidationError(
                "recording.buffer_duration_seconds must be an integer"
            )
        if self.buffer_duration_seconds <= 0:
            raise ConfigurationValidationError("recording.buffer_duration_seconds must be positive")


@dataclass(frozen=True, slots=True)
class ReplayConfig:
    """Persisted replay settings."""

    mpv_executable: str = "mpv"

    def __post_init__(self) -> None:
        if not isinstance(self.mpv_executable, str):
            raise ConfigurationValidationError("replay.mpv_executable must be a string")
        if not self.mpv_executable:
            raise ConfigurationValidationError("replay.mpv_executable must not be empty")


@dataclass(frozen=True, slots=True)
class UiConfig:
    """Reserved UI settings section (populated by a later UI phase)."""


@dataclass(frozen=True, slots=True)
class QuickReplayConfig:
    """The complete persisted configuration."""

    schema_version: int = CURRENT_SCHEMA_VERSION
    input: InputConfig | None = None
    recording: RecordingConfig = field(default_factory=RecordingConfig)
    replay: ReplayConfig = field(default_factory=ReplayConfig)
    ui: UiConfig = field(default_factory=UiConfig)

    def __post_init__(self) -> None:
        if isinstance(self.schema_version, bool) or not isinstance(self.schema_version, int):
            raise ConfigurationValidationError("schema_version must be an integer")
        if self.schema_version != CURRENT_SCHEMA_VERSION:
            raise UnsupportedConfigVersionError(
                f"unsupported schema_version {self.schema_version}; "
                f"expected {CURRENT_SCHEMA_VERSION}"
            )
