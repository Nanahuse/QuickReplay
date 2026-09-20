"""Camera enumeration by probing a bounded range of device indices.

OpenCV does not expose a portable camera name enumeration, so each index is
opened, checked with ``isOpened`` and released again.  No capture handle is
kept after discovery, and no native object escapes this module.
"""

from quickreplay.input.camera.backend import (
    CameraBackend,
    OpenCvCameraBackend,
    resolve_backend_code,
)
from quickreplay.input.models import CameraInputDescriptor

DEFAULT_MAX_CAMERA_DEVICES = 10
"""Number of device indices probed by default."""


def discover_cameras(
    *,
    backend: str = "any",
    max_devices: int = DEFAULT_MAX_CAMERA_DEVICES,
    camera_backend: CameraBackend | None = None,
) -> tuple[CameraInputDescriptor, ...]:
    """Return the cameras opened successfully in ``0 .. max_devices - 1``."""
    if max_devices <= 0:
        raise ValueError(f"max_devices must be positive, got {max_devices}")
    api_preference = resolve_backend_code(backend)
    active = camera_backend or OpenCvCameraBackend()
    descriptors: list[CameraInputDescriptor] = []
    for device_index in range(max_devices):
        capture = active.open_capture(device_index, api_preference)
        try:
            if capture.is_opened():
                descriptors.append(
                    CameraInputDescriptor(
                        device_name=f"Camera {device_index}", device_index=device_index
                    )
                )
        finally:
            capture.release()
    return tuple(descriptors)
