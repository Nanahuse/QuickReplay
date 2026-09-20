"""Errors raised by the replay asset component.

These wrap low-level PyAV/IO failures so that the application layer never sees
raw library exceptions.  Mapping to
:class:`~quickreplay.recording.models.WorkerErrorCode` happens in a later phase.
"""


class ReplayAssetError(RuntimeError):
    """Base class for replay asset component errors."""


class EmptyReplaySnapshotError(ReplayAssetError):
    """A replay snapshot without segments cannot produce a replay asset."""


class ReplaySegmentError(ReplayAssetError):
    """A source segment is missing, unreadable or out of chronological order."""


class ReplayStreamMismatchError(ReplayAssetError):
    """Segments do not share a stream-copy compatible layout."""


class ReplayRemuxError(ReplayAssetError):
    """Remuxing or publishing a replay asset failed."""
