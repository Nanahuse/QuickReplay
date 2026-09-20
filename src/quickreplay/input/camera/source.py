"""Camera input source built on OpenCV.

A :class:`CameraInputSource` owns exactly one capture device and produces
video-only :class:`~quickreplay.input.models.VideoFrame` values in ``BGR24``.
The camera has no audio in this phase, so ``stream_info.audio`` is always
``None``.

OpenCV reports the frame rate as a rounded float, so it is converted to an
exact :class:`~fractions.Fraction` and the actual resolution is taken from the
frame itself.  Frame timestamps use a monotonic clock because live capture has
no source timestamp comparable to NDI.
"""

from collections.abc import Callable
from fractions import Fraction

import numpy as np

from quickreplay.input.camera.backend import (
    DEFAULT_CLOCK_NS,
    CameraBackend,
    CameraCapture,
    CameraProperty,
    OpenCvCameraBackend,
    camera_fps_to_fraction,
    resolve_backend_code,
)
from quickreplay.input.camera.errors import (
    CameraCaptureError,
    CameraFormatError,
    CameraOpenError,
)
from quickreplay.input.models import (
    CameraInputConfig,
    StreamInfo,
    VideoFrame,
    VideoStreamInfo,
)

BGR_COMPONENTS = 3


class CameraInputSource:
    """An :class:`~quickreplay.input.source.InputSource` backed by a camera."""

    def __init__(
        self,
        config: CameraInputConfig,
        *,
        backend: CameraBackend | None = None,
        clock_ns: Callable[[], int] = DEFAULT_CLOCK_NS,
    ) -> None:
        self._config = config
        self._backend: CameraBackend = backend or OpenCvCameraBackend()
        self._clock_ns = clock_ns
        self._capture: CameraCapture | None = None
        self._stream_info: StreamInfo | None = None
        self._video_size: tuple[int, int] | None = None
        self._fps: Fraction | None = None

    @property
    def stream_info(self) -> StreamInfo | None:
        """The actual format, or ``None`` until the first frame."""
        return self._stream_info

    def open(self) -> None:
        """Open the device and request the configured mode, if any."""
        if self._capture is not None:
            raise CameraOpenError(f"camera {self._config.device_index} is already open")
        api_preference = resolve_backend_code(self._config.backend)
        capture = self._backend.open_capture(self._config.device_index, api_preference)
        try:
            if not capture.is_opened():
                raise CameraOpenError(
                    f"could not open camera {self._config.device_index} "
                    f"with backend {self._config.backend!r}"
                )
            self._request_mode(capture)
            self._capture = capture
        except BaseException:
            capture.release()
            raise

    def read(self) -> VideoFrame | None:
        """Return the next BGR24 frame, or raise if the camera stops delivering."""
        capture = self._require_open()
        ok, frame = capture.read()
        if not ok or frame is None:
            raise CameraCaptureError(f"camera {self._config.device_index} did not provide a frame")
        timestamp_ns = self._clock_ns()
        data = self._owned_frame(frame)
        height, width = int(data.shape[0]), int(data.shape[1])
        if self._stream_info is None:
            self._establish_stream_info(capture, width, height)
        elif (width, height) != self._video_size:
            raise CameraFormatError(
                f"camera frame size changed from {self._video_size} to {(width, height)}"
            )
        fps = self._fps
        assert fps is not None
        return VideoFrame(
            timestamp_ns=timestamp_ns,
            width=width,
            height=height,
            fps=fps,
            pixel_format="BGR24",
            data=data,
        )

    def close(self) -> None:
        """Release the capture device.  Safe to call multiple times."""
        capture = self._capture
        self._capture = None
        if capture is not None:
            capture.release()

    # -- internals ---------------------------------------------------------
    def _request_mode(self, capture: CameraCapture) -> None:
        mode = self._config.mode
        if mode is None:
            return
        capture.set(CameraProperty.FRAME_WIDTH, float(mode.width))
        capture.set(CameraProperty.FRAME_HEIGHT, float(mode.height))
        capture.set(CameraProperty.FPS, float(mode.fps))

    def _establish_stream_info(self, capture: CameraCapture, width: int, height: int) -> None:
        fps = self._resolve_fps(capture)
        self._video_size = (width, height)
        self._fps = fps
        self._stream_info = StreamInfo(
            video=VideoStreamInfo(width=width, height=height, fps=fps, pixel_format="BGR24"),
            audio=None,
        )

    def _resolve_fps(self, capture: CameraCapture) -> Fraction:
        """Read the actual frame rate, falling back to the requested mode.

        A camera that cannot report a usable ``CAP_PROP_FPS`` still captures
        frames; if the caller requested an explicit :class:`CameraMode` FPS we
        use it rather than failing the open.  Without a requested mode an
        invalid report is an error, and ``60`` is never assumed.
        """
        reported = capture.get(CameraProperty.FPS)
        try:
            return camera_fps_to_fraction(float(reported))
        except CameraFormatError:
            mode = self._config.mode
            if mode is not None:
                return mode.fps
            raise

    def _owned_frame(self, frame: object) -> np.ndarray:
        if not isinstance(frame, np.ndarray):
            raise CameraFormatError("camera frame is not a numpy.ndarray")
        if frame.dtype != np.uint8 or frame.ndim != 3 or frame.shape[2] != BGR_COMPONENTS:
            raise CameraFormatError(
                f"camera frame must be uint8 (height, width, {BGR_COMPONENTS}); "
                f"got shape {frame.shape} dtype {frame.dtype}"
            )
        if frame.flags["C_CONTIGUOUS"]:
            return frame
        return np.ascontiguousarray(frame)

    def _require_open(self) -> CameraCapture:
        if self._capture is None:
            raise CameraOpenError(f"camera {self._config.device_index} is not open")
        return self._capture
