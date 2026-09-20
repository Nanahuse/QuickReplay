"""Errors raised by the recording component.

These wrap low-level PyAV/IO failures so that the application layer never sees
raw library exceptions.  Mapping to :class:`~quickreplay.recording.models.WorkerErrorCode`
happens in a later phase.
"""


class SegmentRecorderError(RuntimeError):
    """Base class for segment recording errors."""


class SegmentFormatError(SegmentRecorderError):
    """An input frame does not match the recording session's stream format."""


class SegmentTimestampError(SegmentRecorderError):
    """A frame timestamp violates the session timeline constraints."""


class SegmentEncodingError(SegmentRecorderError):
    """Encoding a segment failed."""


class SegmentMuxError(SegmentRecorderError):
    """Writing or finalizing a segment container failed."""
