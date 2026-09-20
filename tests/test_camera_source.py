"""CameraInputSource behaviour: lifecycle, actual format, errors and formats."""

from fractions import Fraction

import cv2
import numpy as np
import pytest
from fake_camera import FakeCameraBackend, FakeCapture, bgr_frame

from quickreplay.input.camera.backend import CameraProperty
from quickreplay.input.camera.errors import (
    CameraCaptureError,
    CameraFormatError,
    CameraOpenError,
)
from quickreplay.input.camera.source import CameraInputSource
from quickreplay.input.models import CameraInputConfig, CameraMode, VideoFrame


def _config(*, mode: CameraMode | None = None, backend: str = "any", index: int = 0):
    return CameraInputConfig(
        device_name=f"Camera {index}", device_index=index, backend=backend, mode=mode
    )


def _source(
    capture: FakeCapture, *, mode: CameraMode | None = None, clock=lambda: 0
) -> CameraInputSource:
    backend = FakeCameraBackend(lambda _index, _api: capture)
    return CameraInputSource(_config(mode=mode), backend=backend, clock_ns=clock)


def _capture(
    *,
    width: int,
    height: int,
    fps: float = 60.0,
    frames: int = 1,
    opened: bool = True,
    set_results: dict[CameraProperty, bool] | None = None,
) -> FakeCapture:
    return FakeCapture(
        opened=opened,
        frames=[bgr_frame(width, height, index) for index in range(frames)],
        properties={
            CameraProperty.FPS: fps,
            CameraProperty.FRAME_WIDTH: float(width),
            CameraProperty.FRAME_HEIGHT: float(height),
        },
        set_results=set_results,
    )


def _array(frame: VideoFrame) -> np.ndarray:
    data = frame.data
    assert isinstance(data, np.ndarray)
    return data


def test_stream_info_is_lazy_and_uses_actual_format() -> None:
    capture = _capture(width=640, height=480, fps=60000 / 1001)
    source = _source(capture)
    source.open()
    try:
        assert source.stream_info is None

        frame = source.read()

        assert isinstance(frame, VideoFrame)
        info = source.stream_info
        assert info is not None
        assert info.video.width == 640
        assert info.video.height == 480
        assert info.video.fps == Fraction(60000, 1001)
        assert info.video.pixel_format == "BGR24"
        assert info.audio is None
    finally:
        source.close()


def test_actual_resolution_overrides_requested_mode() -> None:
    mode = CameraMode(width=1920, height=1080, fps=Fraction(60, 1))
    # The camera rejects the requested mode, so the actual format must win.
    capture = _capture(
        width=1280,
        height=720,
        fps=60000 / 1001,
        set_results={
            CameraProperty.FRAME_WIDTH: False,
            CameraProperty.FRAME_HEIGHT: False,
            CameraProperty.FPS: False,
        },
    )
    source = _source(capture, mode=mode)
    source.open()
    try:
        source.read()
        info = source.stream_info
        assert info is not None
        assert (info.video.width, info.video.height) == (1280, 720)
        assert info.video.fps == Fraction(60000, 1001)
    finally:
        source.close()


def test_mode_request_is_sent_to_the_backend() -> None:
    mode = CameraMode(width=1920, height=1080, fps=Fraction(60, 1))
    capture = _capture(width=1920, height=1080)
    source = _source(capture, mode=mode)

    source.open()
    try:
        assert (CameraProperty.FRAME_WIDTH, 1920.0) in capture.set_calls
        assert (CameraProperty.FRAME_HEIGHT, 1080.0) in capture.set_calls
        assert (CameraProperty.FPS, 60.0) in capture.set_calls
    finally:
        source.close()


def test_without_mode_no_properties_are_set() -> None:
    capture = _capture(width=640, height=480)
    source = _source(capture)
    source.open()
    try:
        assert capture.set_calls == []
    finally:
        source.close()


def test_timestamp_comes_from_the_injected_clock() -> None:
    times = iter([1_000_000_000, 1_016_666_667, 1_033_333_333])
    capture = _capture(width=64, height=36, frames=3)
    source = _source(capture, clock=lambda: next(times))
    source.open()
    try:
        timestamps = []
        for _ in range(3):
            frame = source.read()
            assert frame is not None
            timestamps.append(frame.timestamp_ns)
        assert timestamps == [1_000_000_000, 1_016_666_667, 1_033_333_333]
    finally:
        source.close()


def test_bgr_payload_contract() -> None:
    capture = _capture(width=8, height=4)
    source = _source(capture)
    source.open()
    try:
        frame = source.read()
        assert isinstance(frame, VideoFrame)
        data = _array(frame)
        assert frame.pixel_format == "BGR24"
        assert data.dtype == np.uint8
        assert data.shape == (4, 8, 3)
    finally:
        source.close()


def test_read_failure_raises_capture_error() -> None:
    capture = _capture(width=4, height=2)
    source = _source(capture)
    source.open()
    try:
        source.read()
        with pytest.raises(CameraCaptureError):
            source.read()
    finally:
        source.close()


def test_invalid_fps_without_mode_is_rejected() -> None:
    capture = FakeCapture(
        opened=True, frames=[bgr_frame(4, 2)], properties={CameraProperty.FPS: 0.0}
    )
    source = _source(capture)
    source.open()
    try:
        with pytest.raises(CameraFormatError):
            source.read()
    finally:
        source.close()


def test_invalid_fps_falls_back_to_requested_mode() -> None:
    mode = CameraMode(width=4, height=2, fps=Fraction(30, 1))
    capture = FakeCapture(
        opened=True,
        frames=[bgr_frame(4, 2)],
        properties={CameraProperty.FPS: 0.0},
        set_results={CameraProperty.FPS: False},
    )
    source = _source(capture, mode=mode)
    source.open()
    try:
        source.read()
        info = source.stream_info
        assert info is not None
        assert info.video.fps == Fraction(30, 1)
    finally:
        source.close()


def test_frame_size_change_is_rejected() -> None:
    capture = FakeCapture(
        opened=True,
        frames=[bgr_frame(640, 480), bgr_frame(1280, 720)],
        properties={CameraProperty.FPS: 60.0},
    )
    source = _source(capture)
    source.open()
    try:
        source.read()
        with pytest.raises(CameraFormatError):
            source.read()
    finally:
        source.close()


def test_open_failure_releases_the_capture() -> None:
    capture = FakeCapture(opened=False)
    source = _source(capture)

    with pytest.raises(CameraOpenError):
        source.open()

    assert capture.release_count == 1
    source.close()  # safe after a failed open
    assert capture.release_count == 1


def test_double_open_is_rejected() -> None:
    capture = _capture(width=4, height=2)
    source = _source(capture)
    source.open()
    try:
        with pytest.raises(CameraOpenError):
            source.open()
    finally:
        source.close()


def test_close_is_idempotent_and_releases_once() -> None:
    capture = _capture(width=4, height=2)
    source = _source(capture)
    source.open()

    source.close()
    source.close()

    assert capture.release_count == 1
    with pytest.raises(CameraOpenError):
        source.read()


def test_configured_backend_is_used_for_capture() -> None:
    seen: list[tuple[int, int]] = []

    def factory(index: int, api_preference: int) -> FakeCapture:
        seen.append((index, api_preference))
        return FakeCapture(opened=True)

    backend = FakeCameraBackend(factory)
    source = CameraInputSource(_config(backend="dshow", index=2), backend=backend)
    source.open()
    try:
        assert seen == [(2, int(cv2.CAP_DSHOW))]
    finally:
        source.close()
