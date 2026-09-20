"""Errors raised by the camera input component.

These wrap low-level OpenCV/IO failures so that the application layer never
sees raw library exceptions.  Mapping to
:class:`~quickreplay.recording.models.WorkerErrorCode` happens in a later phase.
"""


class CameraInputError(RuntimeError):
    """Base class for camera input errors."""


class CameraNotFoundError(CameraInputError):
    """The requested camera device is not available."""


class CameraOpenError(CameraInputError):
    """Opening the camera device failed."""


class CameraCaptureError(CameraInputError):
    """Reading a frame from the camera failed or was interrupted."""


class CameraBackendError(CameraInputError):
    """The requested OpenCV capture backend is unknown or unavailable."""


class CameraFormatError(CameraInputError):
    """The camera frame or reported format is not usable."""
