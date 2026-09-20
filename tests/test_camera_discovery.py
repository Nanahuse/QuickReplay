"""Camera discovery: bounded probing, descriptors and handle release."""

import pytest
from fake_camera import FakeCameraBackend, FakeCapture

from quickreplay.input.camera.discovery import (
    DEFAULT_MAX_CAMERA_DEVICES,
    discover_cameras,
)
from quickreplay.input.models import CameraInputDescriptor


def test_discovery_returns_only_available_devices_and_releases() -> None:
    backend = FakeCameraBackend(lambda index, _api: FakeCapture(opened=index in {1, 2}))

    descriptors = discover_cameras(backend="any", max_devices=4, camera_backend=backend)

    assert descriptors == (
        CameraInputDescriptor(device_name="Camera 1", device_index=1),
        CameraInputDescriptor(device_name="Camera 2", device_index=2),
    )
    assert len(backend.captures) == 4
    assert all(capture.release_count == 1 for capture in backend.captures)


def test_discovery_respects_max_devices() -> None:
    backend = FakeCameraBackend(lambda _index, _api: FakeCapture(opened=True))

    descriptors = discover_cameras(max_devices=3, camera_backend=backend)

    assert [descriptor.device_index for descriptor in descriptors] == [0, 1, 2]
    assert len(backend.captures) == 3


def test_discovery_rejects_non_positive_max_devices() -> None:
    backend = FakeCameraBackend(lambda _index, _api: FakeCapture(opened=True))

    with pytest.raises(ValueError):
        discover_cameras(max_devices=0, camera_backend=backend)


def test_default_max_devices_is_bounded() -> None:
    assert DEFAULT_MAX_CAMERA_DEVICES == 10
