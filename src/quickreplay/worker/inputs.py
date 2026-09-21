"""Input source creation and discovery for the worker process.

Native NDI / OpenCV objects are created here, inside the worker process only.
Main never receives a native handle or a frame.
"""

from dataclasses import dataclass

from quickreplay.input.camera.discovery import discover_cameras
from quickreplay.input.camera.source import CameraInputSource
from quickreplay.input.models import (
    CameraInputConfig,
    InputConfig,
    InputDescriptor,
    NdiInputConfig,
)
from quickreplay.input.ndi.discovery import discover_ndi_sources
from quickreplay.input.ndi.source import NdiInputSource
from quickreplay.input.source import InputSource
from quickreplay.worker.errors import WorkerPipelineError


@dataclass(frozen=True, slots=True)
class InputSourceHandle:
    """An opened-capable source together with whether it can carry audio."""

    source: InputSource
    supports_audio: bool


def create_input_source(config: InputConfig) -> InputSource:
    """Create the matching :class:`InputSource` for *config*."""
    match config:
        case NdiInputConfig():
            return NdiInputSource(config)
        case CameraInputConfig():
            return CameraInputSource(config)
    raise WorkerPipelineError(f"unsupported input configuration: {config!r}")


def input_supports_audio(config: InputConfig) -> bool:
    """Whether the configured input can carry audio (NDI yes, Camera no)."""
    return isinstance(config, NdiInputConfig)


def open_input_source(config: InputConfig) -> InputSourceHandle:
    """Create a source and describe its audio capability."""
    return InputSourceHandle(
        source=create_input_source(config),
        supports_audio=input_supports_audio(config),
    )


def discover_inputs(*, camera_backend: str = "any") -> tuple[InputDescriptor, ...]:
    """Discover NDI and camera inputs, skipping unavailable providers.

    A provider that cannot be queried is not a fatal error; discovery returns
    whatever the remaining providers reported.  ``camera_backend`` selects the
    OpenCV backend used to probe cameras.
    """
    discovered: list[InputDescriptor] = []
    providers = (
        discover_ndi_sources,
        lambda: discover_cameras(backend=camera_backend),
    )
    for provider in providers:
        try:
            discovered.extend(provider())
        except Exception:  # noqa: BLE001 - provider failures are non-fatal
            continue
    return tuple(discovered)
