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


class ReplayControllerError(RuntimeError):
    """Base class for replay playback (mpv) controller errors."""


class MpvExecutableNotFoundError(ReplayControllerError):
    """The configured mpv executable could not be started."""


class MpvStartupError(ReplayControllerError):
    """mpv did not become ready for playback within the startup timeout."""


class MpvIpcError(ReplayControllerError):
    """The mpv JSON IPC connection failed."""


class MpvCommandError(ReplayControllerError):
    """mpv returned a non-success response to a command."""

    def __init__(self, error: str, command: object) -> None:
        super().__init__(f"mpv command {command!r} failed: {error}")
        self.error = error
        self.command = command


class MpvCommandTimeoutError(ReplayControllerError):
    """mpv did not answer a command within the command timeout."""


class MpvProcessExitedError(ReplayControllerError):
    """The mpv process exited while the controller still expected it."""


class MpvPropertyUnavailableError(ReplayControllerError):
    """An mpv property is not available (for example ``time-pos`` before load)."""
