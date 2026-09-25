"""Errors raised by the NDI input component.

These wrap low-level binding/runtime failures so that the application layer
never sees raw library exceptions.  Mapping to
:class:`~quickreplay.recording.models.WorkerErrorCode` happens in a later phase.
"""


class NdiInputError(RuntimeError):
    """Base class for NDI input errors."""


class NdiInitializationError(NdiInputError):
    """The NDI runtime could not be loaded or initialized."""


class NdiSourceNotFoundError(NdiInputError):
    """The requested NDI source was not present during discovery."""


class NdiReceiverError(NdiInputError):
    """Creating, using or destroying an NDI receiver failed."""


class NdiCaptureError(NdiInputError):
    """Capturing a frame failed, for example after a source disconnect."""


class NdiUnsupportedFormatError(NdiInputError):
    """A captured frame uses a format the recording pipeline cannot consume."""


class NdiFormatChangeError(NdiInputError):
    """The stream format changed mid-session and cannot be silently mixed."""
