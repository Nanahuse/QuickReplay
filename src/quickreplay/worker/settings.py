"""Runtime settings for the recorder worker.

These are runtime knobs, not persisted configuration.  Every value can be
injected from tests so timing-sensitive behaviour stays deterministic.
"""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class RecorderWorkerSettings:
    """Tunables for one recorder worker process."""

    working_directory: Path

    buffer_duration_ns: int = 120_000_000_000
    """Ring buffer retention window (default 120 seconds)."""

    segment_duration_ns: int = 2_000_000_000
    """Target duration of one segment file."""

    video_queue_capacity: int = 64
    audio_queue_capacity: int = 64

    av_reorder_holdback_ns: int = 500_000_000
    """How long the encode side waits for the other stream before emitting."""

    stream_probe_window_ns: int = 500_000_000
    """Control-time window after first video before fixing video-only format."""

    stream_start_timeout_ns: int = 5_000_000_000
    """Control timeout for the first video frame, measured after source.open()."""

    metrics_interval_ns: int = 1_000_000_000

    freeze_grace_ns: int = 1_500_000_000
    """How long ``stop`` waits for the capture thread before interrupting it."""

    drain_timeout_ns: int = 5_000_000_000
    """How long ``stop`` waits for the encode thread to finish draining."""

    @property
    def buffer_root(self) -> Path:
        """Root directory holding per-session segment directories."""
        return self.working_directory / "buffer"

    @property
    def replay_root(self) -> Path:
        """Root directory holding per-request replay asset directories."""
        return self.working_directory / "replay"

    @property
    def freeze_grace_seconds(self) -> float:
        return self.freeze_grace_ns / 1_000_000_000

    @property
    def drain_timeout_seconds(self) -> float:
        return self.drain_timeout_ns / 1_000_000_000

    @property
    def stream_start_timeout_seconds(self) -> float:
        return self.stream_start_timeout_ns / 1_000_000_000
