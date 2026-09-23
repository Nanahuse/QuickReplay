"""Input source creation and discovery for the worker process.

Native NDI objects are created here, inside the worker process only. Main
never receives a native handle or a frame.
"""

from dataclasses import dataclass

from quickreplay.input.models import InputConfig, InputDescriptor
from quickreplay.input.ndi.discovery import discover_ndi_sources
from quickreplay.input.ndi.source import NdiInputSource
from quickreplay.input.source import InputSource


@dataclass(frozen=True, slots=True)
class InputSourceHandle:
    """An opened-capable source together with whether it can carry audio."""

    source: InputSource
    supports_audio: bool


def create_input_source(config: InputConfig) -> InputSource:
    """Create the production input source for *config*."""
    return NdiInputSource(config)


def input_supports_audio(config: InputConfig) -> bool:
    """NDI sources can carry audio; stream probing detects video-only inputs."""
    del config
    return True


def open_input_source(config: InputConfig) -> InputSourceHandle:
    """Create a source and describe its audio capability."""
    return InputSourceHandle(
        source=create_input_source(config),
        supports_audio=input_supports_audio(config),
    )


def discover_inputs() -> tuple[InputDescriptor, ...]:
    """Discover NDI inputs, treating discovery failure as an empty result."""
    try:
        return discover_ndi_sources()
    except Exception:  # noqa: BLE001 - provider failures are non-fatal
        return ()
