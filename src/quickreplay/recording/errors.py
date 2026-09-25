"""Errors raised by the recording component.

These wrap low-level PyAV/IO failures so that the application layer never sees
raw library exceptions.  Mapping to :class:`~quickreplay.recording.models.WorkerErrorCode`
happens in a later phase.
"""

from pathlib import Path


class RecordingError(RuntimeError):
    """Base class for recording component errors."""


class SegmentRecorderError(RecordingError):
    """Base class for segment recording errors."""


class SegmentFormatError(SegmentRecorderError):
    """An input frame does not match the recording session's stream format."""


class SegmentTimestampError(SegmentRecorderError):
    """A frame timestamp violates the session timeline constraints."""


class SegmentEncodingError(SegmentRecorderError):
    """Encoding a segment failed."""


class SegmentMuxError(SegmentRecorderError):
    """Writing or finalizing a segment container failed."""


class RingStorageError(RecordingError):
    """Base class for ring storage errors."""


class SegmentOrderError(RingStorageError):
    """A segment was added out of chronological order or with a duplicate id."""


class SegmentDeleteError(RingStorageError):
    """Deleting one or more expired segment files failed."""

    def __init__(self, paths: tuple[Path, ...]) -> None:
        super().__init__(f"failed to delete {len(paths)} segment file(s): {paths}")
        self.paths = paths
