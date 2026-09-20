"""Camera input implementation.

Everything that depends on OpenCV lives in this package.  ``cv2`` is imported
lazily, so the rest of QuickReplay never loads OpenCV unless a camera is
actually used.
"""

from quickreplay.input.camera.backend import camera_fps_to_fraction, cv2_available
from quickreplay.input.camera.discovery import (
    DEFAULT_MAX_CAMERA_DEVICES,
    discover_cameras,
)
from quickreplay.input.camera.errors import (
    CameraBackendError,
    CameraCaptureError,
    CameraFormatError,
    CameraInputError,
    CameraNotFoundError,
    CameraOpenError,
)
from quickreplay.input.camera.source import CameraInputSource

__all__ = [
    "DEFAULT_MAX_CAMERA_DEVICES",
    "CameraBackendError",
    "CameraCaptureError",
    "CameraFormatError",
    "CameraInputError",
    "CameraInputSource",
    "CameraNotFoundError",
    "CameraOpenError",
    "camera_fps_to_fraction",
    "cv2_available",
    "discover_cameras",
]
