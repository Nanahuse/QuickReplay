"""Flet-independent settings editing logic.

The settings editor never mutates a :class:`~quickreplay.configuration.models.QuickReplayConfig`
directly.  A :class:`SettingsDraft` holds the raw text entered in the dialog
(which may be temporarily invalid while typing) and is converted into a new
candidate configuration only when the user presses *Apply*.  Nothing here
imports Flet, so the whole draft -> validate -> config flow is headless-testable.
"""

import re
from dataclasses import dataclass, replace
from fractions import Fraction

from quickreplay.configuration.errors import ConfigurationValidationError
from quickreplay.configuration.models import (
    QuickReplayConfig,
    RecordingConfig,
    ReplayConfig,
)
from quickreplay.input.models import CameraInputConfig, CameraMode

_INTEGER_PATTERN = re.compile(r"^[+-]?[0-9]+$")

RESTART_REQUIRED_MESSAGE = (
    "Settings saved. Restart QuickReplay to apply recording/replay runtime changes."
)
CAMERA_MODE_MESSAGE = "Settings saved. The camera mode will be used the next time recording starts."
SETTINGS_SAVED_MESSAGE = "Settings saved."


@dataclass(slots=True)
class SettingsDraft:
    """Raw, possibly-invalid text mirroring the settings dialog fields.

    Values are converted to the domain model only on Apply, so partial input
    such as ``""`` or ``"abc"`` is representable.
    """

    use_explicit_camera_mode: bool = False
    camera_width: str = ""
    camera_height: str = ""
    camera_fps_numerator: str = ""
    camera_fps_denominator: str = ""
    buffer_duration_seconds: str = ""
    mpv_executable: str = ""
    camera_available: bool = False
    camera_label: str = ""


@dataclass(frozen=True, slots=True)
class SettingsFieldError:
    """A validation error tied to a draft field."""

    field: str
    message: str


@dataclass(frozen=True, slots=True)
class SettingsValidation:
    """The outcome of turning a draft into a candidate configuration."""

    config: QuickReplayConfig | None
    errors: tuple[SettingsFieldError, ...]


@dataclass(frozen=True, slots=True)
class SettingsApplyResult:
    """The outcome of applying a draft (validation, save and status)."""

    ok: bool
    message: str = ""
    restart_required: bool = False
    errors: tuple[SettingsFieldError, ...] = ()


def draft_from_config(config: QuickReplayConfig, *, camera_input: object | None) -> SettingsDraft:
    """Build a draft from the persisted config and the currently selected input."""
    if isinstance(camera_input, CameraInputConfig):
        mode = camera_input.mode
        label = f"{camera_input.device_name} (#{camera_input.device_index})"
    else:
        mode = None
        label = ""
    return SettingsDraft(
        use_explicit_camera_mode=mode is not None,
        camera_width=str(mode.width) if mode is not None else "",
        camera_height=str(mode.height) if mode is not None else "",
        camera_fps_numerator=str(mode.fps.numerator) if mode is not None else "",
        camera_fps_denominator=str(mode.fps.denominator) if mode is not None else "",
        buffer_duration_seconds=str(config.recording.buffer_duration_seconds),
        mpv_executable=config.replay.mpv_executable,
        camera_available=isinstance(camera_input, CameraInputConfig),
        camera_label=label,
    )


def build_settings_config(
    draft: SettingsDraft,
    config: QuickReplayConfig,
    *,
    camera_input: object | None,
) -> SettingsValidation:
    """Validate a draft and build the candidate configuration.

    ``camera_input`` is the input currently selected in the main window.  When
    it is a :class:`CameraInputConfig` the capture mode is edited on it;
    otherwise the camera section is inert and ``config.input`` is preserved.
    """
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

    camera_config = camera_input if isinstance(camera_input, CameraInputConfig) else None
    new_mode: CameraMode | None = None
    if camera_config is not None and draft.use_explicit_camera_mode:
        width = _parse_positive_int(draft.camera_width, "camera_width", "Width", errors)
        height = _parse_positive_int(draft.camera_height, "camera_height", "Height", errors)
        numerator = _parse_positive_int(
            draft.camera_fps_numerator, "camera_fps_numerator", "FPS numerator", errors
        )
        denominator = _parse_positive_int(
            draft.camera_fps_denominator, "camera_fps_denominator", "FPS denominator", errors
        )
        if width is not None and height is not None and numerator is not None and denominator:
            try:
                new_mode = CameraMode(
                    width=width, height=height, fps=Fraction(numerator, denominator)
                )
            except ValueError as exc:
                errors.append(SettingsFieldError("camera_fps_denominator", str(exc)))

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

    input_config = config.input
    if camera_config is not None:
        input_config = replace(camera_config, mode=new_mode)
    candidate = replace(config, input=input_config, recording=recording, replay=replay)
    return SettingsValidation(config=candidate, errors=())


def restart_required(current: QuickReplayConfig, candidate: QuickReplayConfig) -> bool:
    """Whether applying *candidate* requires an application restart.

    Only the recording (buffer) and replay (mpv executable) runtime settings are
    built once at bootstrap; a camera mode change applies on the next start.
    """
    return current.recording != candidate.recording or current.replay != candidate.replay


def apply_message(*, restart: bool, input_changed: bool) -> str:
    """Status text shown after a successful apply."""
    if restart:
        return RESTART_REQUIRED_MESSAGE
    if input_changed:
        return CAMERA_MODE_MESSAGE
    return SETTINGS_SAVED_MESSAGE


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
