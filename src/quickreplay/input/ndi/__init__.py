"""NDI input implementation.

Everything that depends on the native ``NDIlib`` binding lives in this package
and is imported lazily, so the rest of QuickReplay never initializes NDI unless
an NDI source is actually used.
"""

from quickreplay.input.ndi.backend import ndi_available
from quickreplay.input.ndi.discovery import discover_ndi_sources
from quickreplay.input.ndi.errors import (
    NdiCaptureError,
    NdiFormatChangeError,
    NdiInitializationError,
    NdiInputError,
    NdiReceiverError,
    NdiSourceNotFoundError,
    NdiUnsupportedFormatError,
)
from quickreplay.input.ndi.source import NdiInputSource

__all__ = [
    "NdiCaptureError",
    "NdiFormatChangeError",
    "NdiInitializationError",
    "NdiInputError",
    "NdiInputSource",
    "NdiReceiverError",
    "NdiSourceNotFoundError",
    "NdiUnsupportedFormatError",
    "discover_ndi_sources",
    "ndi_available",
]
