"""Recorder worker: a long-lived process that records segments and builds replays.

The worker owns all native resources (input receivers, encoders, muxers) and
communicates with the main process only through picklable commands and events.
"""

from quickreplay.worker.inputs import (
    InputSourceHandle,
    create_input_source,
    discover_inputs,
    input_supports_audio,
    open_input_source,
)
from quickreplay.worker.process import (
    RecorderWorkerProcess,
    spawn_context,
    worker_process_main,
)
from quickreplay.worker.runtime import RecorderWorkerRuntime
from quickreplay.worker.settings import RecorderWorkerSettings

__all__ = [
    "InputSourceHandle",
    "RecorderWorkerProcess",
    "RecorderWorkerRuntime",
    "RecorderWorkerSettings",
    "create_input_source",
    "discover_inputs",
    "input_supports_audio",
    "open_input_source",
    "spawn_context",
    "worker_process_main",
]
