"""Conversion from persisted configuration to runtime settings.

Only stable user settings are mapped.  Internal runtime tuning (queue
capacities, hold-back windows, timeouts, segment duration, ...) keeps its
existing defaults.  ``working_directory`` comes from the runtime environment,
never from the configuration file.
"""

from pathlib import Path

from quickreplay.application.models import ApplicationControllerSettings
from quickreplay.configuration.models import QuickReplayConfig
from quickreplay.replay.controller import ReplayControllerSettings
from quickreplay.units import NANOSECONDS_PER_SECOND
from quickreplay.worker.settings import RecorderWorkerSettings


def build_application_settings(
    config: QuickReplayConfig,
    *,
    working_directory: Path,
) -> ApplicationControllerSettings:
    """Build runtime settings from *config* and a runtime working directory."""
    worker_settings = RecorderWorkerSettings(
        working_directory=working_directory,
        buffer_duration_ns=config.recording.buffer_duration_seconds * NANOSECONDS_PER_SECOND,
    )
    replay_settings = ReplayControllerSettings(
        mpv_executable=config.replay.mpv_executable,
    )
    return ApplicationControllerSettings(worker=worker_settings, replay=replay_settings)
