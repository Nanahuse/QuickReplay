"""Flet-independent settings editing and validation logic."""

import re
from dataclasses import dataclass, replace

from quickreplay.configuration.errors import ConfigurationValidationError
from quickreplay.configuration.models import QuickReplayConfig, RecordingConfig, ReplayConfig

_INTEGER_PATTERN = re.compile(r"^[+-]?[0-9]+$")

RESTART_REQUIRED_MESSAGE = (
    "Settings saved. Restart QuickReplay to apply recording/replay runtime changes."
)
SETTINGS_SAVED_MESSAGE = "Settings saved."


@dataclass(slots=True)
class SettingsDraft:
    """Raw text values mirrored from the settings fields until Apply."""

    buffer_duration_seconds: str = ""
    mpv_executable: str = ""


@dataclass(frozen=True, slots=True)
class SettingsFieldError:
    """A validation error tied to a draft field."""

    field: str
    message: str


@dataclass(frozen=True, slots=True)
class SettingsValidation:
    """The outcome of validating a settings draft."""

    config: QuickReplayConfig | None
    errors: tuple[SettingsFieldError, ...]


@dataclass(frozen=True, slots=True)
class SettingsApplyResult:
    """The outcome of applying a draft (validation, save and status)."""

    ok: bool
    message: str = ""
    restart_required: bool = False
    errors: tuple[SettingsFieldError, ...] = ()


def draft_from_config(config: QuickReplayConfig) -> SettingsDraft:
    """Build a draft from the persisted configuration."""
    return SettingsDraft(
        buffer_duration_seconds=str(config.recording.buffer_duration_seconds),
        mpv_executable=config.replay.mpv_executable,
    )


def build_settings_config(draft: SettingsDraft, config: QuickReplayConfig) -> SettingsValidation:
    """Validate a draft and build a candidate preserving the selected input."""
    errors: list[SettingsFieldError] = []
    buffer_seconds = _parse_positive_int(
        draft.buffer_duration_seconds,
        "buffer_duration_seconds",
        "Buffer duration",
        errors,
    )
    mpv_executable = draft.mpv_executable.strip()
    if not mpv_executable:
        errors.append(SettingsFieldError("mpv_executable", "mpv executable must not be empty"))

    recording: RecordingConfig | None = None
    if buffer_seconds is not None:
        try:
            recording = RecordingConfig(buffer_seconds)
        except ConfigurationValidationError as exc:
            errors.append(SettingsFieldError("buffer_duration_seconds", str(exc)))

    replay: ReplayConfig | None = None
    if mpv_executable:
        try:
            replay = ReplayConfig(mpv_executable)
        except ConfigurationValidationError as exc:
            errors.append(SettingsFieldError("mpv_executable", str(exc)))

    if errors or recording is None or replay is None:
        return SettingsValidation(config=None, errors=tuple(errors))
    return SettingsValidation(config=replace(config, recording=recording, replay=replay), errors=())


def restart_required(current: QuickReplayConfig, candidate: QuickReplayConfig) -> bool:
    """Whether the runtime recording/replay settings require a restart."""
    return current.recording != candidate.recording or current.replay != candidate.replay


def apply_message(*, restart: bool) -> str:
    """Status text shown after a successful settings apply."""
    return RESTART_REQUIRED_MESSAGE if restart else SETTINGS_SAVED_MESSAGE


def _parse_positive_int(
    raw: str,
    field: str,
    label: str,
    errors: list[SettingsFieldError],
) -> int | None:
    text = raw.strip()
    if not _INTEGER_PATTERN.match(text):
        errors.append(SettingsFieldError(field, f"{label} must be a positive integer"))
        return None
    value = int(text)
    if value <= 0:
        errors.append(SettingsFieldError(field, f"{label} must be a positive integer"))
        return None
    return value
