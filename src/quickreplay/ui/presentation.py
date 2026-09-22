"""Pure presentation helpers: domain values to display text and control states.

Nothing here imports Flet.  Display formatting may use floats, but the domain
values (:class:`~fractions.Fraction`, nanoseconds) stay the source of truth.
"""

import sys
from dataclasses import dataclass
from fractions import Fraction

from quickreplay.app.state import ApplicationState
from quickreplay.input.models import StreamInfo
from quickreplay.recording.models import RecordingMetrics
from quickreplay.units import NANOSECONDS_PER_SECOND

_EMPTY = "—"

_STATE_LABELS: dict[ApplicationState, str] = {
    ApplicationState.STARTING: "Starting",
    ApplicationState.IDLE: "Idle",
    ApplicationState.RECORDING: "Recording",
    ApplicationState.PREPARING_REPLAY: "Preparing Replay",
    ApplicationState.REPLAY: "Replay",
    ApplicationState.STOPPING: "Stopping",
    ApplicationState.RESUMING: "Resuming",
    ApplicationState.ERROR: "Error",
    ApplicationState.SHUTTING_DOWN: "Shutting Down",
}


def state_label(state: ApplicationState) -> str:
    """Human-readable label for an application state."""
    return _STATE_LABELS[state]


def format_fps(fps: Fraction) -> str:
    """Format a frame rate for display (``60``, ``59.94``, ``29.97``)."""
    if fps.denominator == 1:
        return str(fps.numerator)
    return f"{float(fps):.2f}"


def format_stream_info(stream_info: StreamInfo | None) -> str:
    """Format the video stream summary line."""
    if stream_info is None:
        return _EMPTY
    video = stream_info.video
    return f"{video.width} × {video.height} | {format_fps(video.fps)} fps | {video.pixel_format}"


def format_audio(stream_info: StreamInfo | None) -> str:
    """Format the audio summary line."""
    if stream_info is None:
        return _EMPTY
    audio = stream_info.audio
    if audio is None:
        return "Audio: None"
    if audio.channels == 1:
        layout = "Mono"
    elif audio.channels == 2:
        layout = "Stereo"
    else:
        layout = f"{audio.channels} ch"
    return f"Audio: {audio.sample_rate / 1000:g} kHz / {layout}"


def format_buffer(current_ns: int, maximum_seconds: int) -> str:
    """Format the buffer usage as ``current / maximum s``."""
    return f"{current_ns / NANOSECONDS_PER_SECOND:.1f} / {maximum_seconds} s"


def format_duration_ns(value_ns: int) -> str:
    """Format nanoseconds as ``MM:SS.mmm`` (or ``H:MM:SS.mmm`` for long values)."""
    total_ms = abs(value_ns) // 1_000_000
    millis = total_ms % 1000
    total_seconds = total_ms // 1000
    seconds = total_seconds % 60
    total_minutes = total_seconds // 60
    minutes = total_minutes % 60
    hours = total_minutes // 60
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}.{millis:03d}"
    return f"{minutes:02d}:{seconds:02d}.{millis:03d}"


def format_signed_duration_ns(value_ns: int) -> str:
    """Format a signed duration: ``+00:00.750`` / ``-00:00.750`` / ``00:00.000``."""
    if value_ns > 0:
        return f"+{format_duration_ns(value_ns)}"
    if value_ns < 0:
        return f"-{format_duration_ns(value_ns)}"
    return format_duration_ns(0)


def format_signed_frames(value: int) -> str:
    """Format a frame difference: ``+45`` / ``-12`` / ``0``."""
    if value > 0:
        return f"+{value}"
    return str(value)


def buffer_fraction(current_ns: int, maximum_seconds: int) -> float:
    """Buffer usage clamped to ``0.0 .. 1.0``."""
    if maximum_seconds <= 0:
        return 0.0
    value = (current_ns / NANOSECONDS_PER_SECOND) / maximum_seconds
    return min(1.0, max(0.0, value))


@dataclass(frozen=True, slots=True)
class MetricsView:
    """Display-ready recording metrics."""

    input_fps: str
    recording_fps: str
    buffer: str
    buffer_fraction: float
    segments: str
    drops: str


def metrics_view(
    metrics: RecordingMetrics | None, *, buffer_max_seconds: int
) -> MetricsView | None:
    """Build a :class:`MetricsView`, or ``None`` when no metrics are available."""
    if metrics is None:
        return None
    return MetricsView(
        input_fps=f"{metrics.input_fps:.1f}",
        recording_fps=f"{metrics.recording_fps:.1f}",
        buffer=format_buffer(metrics.buffer_duration_ns, buffer_max_seconds),
        buffer_fraction=buffer_fraction(metrics.buffer_duration_ns, buffer_max_seconds),
        segments=str(metrics.segment_count),
        drops=f"Video {metrics.video_queue_drops} / Audio {metrics.audio_queue_drops}",
    )


@dataclass(frozen=True, slots=True)
class ControlState:
    """Which actions the UI should offer for the current state."""

    input_enabled: bool
    refresh_enabled: bool
    start_enabled: bool
    replay_enabled: bool
    resume_enabled: bool
    settings_enabled: bool
    discovering: bool


def control_state(
    state: ApplicationState, *, has_selection: bool, discovering: bool
) -> ControlState:
    """Derive control enablement from the application state."""
    idle = state == ApplicationState.IDLE
    recording = state == ApplicationState.RECORDING
    replay = state == ApplicationState.REPLAY
    discovery_allowed = idle or recording or replay
    return ControlState(
        input_enabled=idle,
        refresh_enabled=discovery_allowed and not discovering,
        start_enabled=idle and has_selection and not discovering,
        replay_enabled=recording,
        resume_enabled=replay,
        settings_enabled=state != ApplicationState.SHUTTING_DOWN,
        discovering=discovering,
    )


def camera_backend_options(platform: str | None = None) -> tuple[str, ...]:
    """Camera backends offered for the given platform."""
    name = sys.platform if platform is None else platform
    if name.startswith("win"):
        return ("any", "msmf", "dshow")
    if name.startswith("linux"):
        return ("any", "v4l2")
    return ("any",)
