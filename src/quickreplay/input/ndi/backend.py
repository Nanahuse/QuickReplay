"""Thin backend around the ``ndi-python`` binding.

This module is the only place that touches native NDI types.  The rest of the
package depends on :class:`NdiBackend` / :class:`NdiReceiver` and on the plain
:class:`RawVideo` / :class:`RawAudio` / :class:`RawMetadata` dataclasses, so a
fake backend can exercise every code path without an NDI runtime or an NDI
source (see ``tests/fake_ndi.py``).

``NDIlib`` itself is imported lazily, so importing the core package never
initializes NDI or fails on a machine without the runtime.
"""

import threading
from dataclasses import dataclass
from fractions import Fraction
from typing import Any, Protocol

import numpy as np

from quickreplay.input.ndi.errors import (
    NdiCaptureError,
    NdiInitializationError,
    NdiReceiverError,
    NdiUnsupportedFormatError,
)

NDI_TIMESTAMP_TICK_NS = 100
"""NDI timestamps are expressed in 100-nanosecond ticks."""

NDI_RECEIVER_NAME = "QuickReplay"


def ndi_timestamp_to_ns(timestamp_100ns: int) -> int:
    """Convert an NDI 100-nanosecond timestamp to integer nanoseconds."""
    return timestamp_100ns * NDI_TIMESTAMP_TICK_NS


@dataclass(slots=True)
class RawVideo:
    """A captured video frame still backed by native memory.

    ``data`` may be a view onto the native buffer; it must be copied before the
    matching :meth:`NdiReceiver.free_video` call.
    """

    width: int
    height: int
    line_stride: int
    pixel_format: str
    fps: Fraction
    timestamp_ns: int
    data: np.ndarray
    handle: Any


@dataclass(slots=True)
class RawAudio:
    """A captured planar float audio frame still backed by native memory."""

    sample_rate: int
    channels: int
    samples: int
    channel_stride: int
    audio_format: str
    timestamp_ns: int
    data: np.ndarray
    handle: Any


@dataclass(slots=True)
class RawMetadata:
    """A captured metadata frame.  Always discarded by the input source."""

    handle: Any


type RawCapture = RawVideo | RawAudio | RawMetadata | None


class NdiReceiver(Protocol):
    """One receiver carrying both the video and the audio of a source."""

    def capture(self, *, timeout_ms: int) -> RawCapture: ...

    def free_video(self, frame: RawVideo) -> None: ...

    def free_audio(self, frame: RawAudio) -> None: ...

    def free_metadata(self, frame: RawMetadata) -> None: ...

    def source_name(self) -> str: ...

    def destroy(self) -> None: ...


class NdiBackend(Protocol):
    """The native operations the NDI input source needs."""

    def initialize(self) -> None: ...

    def shutdown(self) -> None: ...

    def discover(self, *, timeout_ms: int) -> tuple[str, ...]: ...

    def create_receiver(self, *, source_name: str, timeout_ms: int) -> NdiReceiver: ...


def import_ndi() -> Any:
    """Import and return the ``NDIlib`` module, or raise if unavailable."""
    try:
        import NDIlib  # noqa: PLC0415 - deliberately lazy
    except Exception as exc:  # noqa: BLE001 - ImportError / OSError / DLL errors
        raise NdiInitializationError(f"the NDI runtime is not available: {exc}") from exc
    return NDIlib


def ndi_available() -> bool:
    """Whether the NDI runtime can be imported on this machine."""
    try:
        import_ndi()
    except NdiInitializationError:
        return False
    return True


class _NdiRuntime:
    """Reference-counted ownership of the process-wide NDI runtime.

    ``NDIlib.initialize`` / ``NDIlib.destroy`` are global.  Reference counting
    keeps discovery, receivers and a future second source from destroying the
    runtime while another component still needs it.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._references = 0

    def acquire(self) -> None:
        ndi = import_ndi()
        with self._lock:
            if self._references == 0 and not ndi.initialize():
                raise NdiInitializationError("NDIlib.initialize() failed")
            self._references += 1

    def release(self) -> None:
        with self._lock:
            if self._references == 0:
                return
            self._references -= 1
            if self._references == 0:
                import_ndi().destroy()


_runtime = _NdiRuntime()


class PyNdiBackend:
    """The real backend, backed by the bundled NDI runtime."""

    def initialize(self) -> None:
        _runtime.acquire()

    def shutdown(self) -> None:
        _runtime.release()

    def discover(self, *, timeout_ms: int) -> tuple[str, ...]:
        ndi = import_ndi()
        finder = ndi.find_create_v2()
        if not finder:
            raise NdiInitializationError("could not create an NDI finder")
        try:
            ndi.find_wait_for_sources(finder, timeout_ms)
            sources = ndi.find_get_current_sources(finder)
            return tuple(source.ndi_name for source in sources)
        finally:
            ndi.find_destroy(finder)

    def create_receiver(self, *, source_name: str, timeout_ms: int) -> NdiReceiver:
        ndi = import_ndi()
        settings = ndi.RecvCreateV3()
        source = ndi.Source()
        source.ndi_name = source_name
        settings.source_to_connect_to = source
        settings.color_format = ndi.RECV_COLOR_FORMAT_UYVY_BGRA
        settings.bandwidth = ndi.RECV_BANDWIDTH_HIGHEST
        settings.allow_video_fields = False
        settings.ndi_recv_name = NDI_RECEIVER_NAME
        receiver = ndi.recv_create_v3(settings)
        if not receiver:
            raise NdiReceiverError(f"could not create an NDI receiver for {source_name!r}")
        return PyNdiReceiver(receiver)


class PyNdiReceiver:
    """The real receiver.  One instance owns exactly one native receiver."""

    def __init__(self, receiver: Any) -> None:
        self._receiver = receiver
        self._destroyed = False

    def capture(self, *, timeout_ms: int) -> RawCapture:
        ndi = import_ndi()
        frame_type, video, audio, metadata = ndi.recv_capture_v3(
            self._receiver, timeout_ms, True, True, True
        )
        kind = int(frame_type)
        if kind == int(ndi.FRAME_TYPE_VIDEO):
            return self._video(ndi, video) if video is not None else None
        if kind == int(ndi.FRAME_TYPE_AUDIO):
            return self._audio(ndi, audio) if audio is not None else None
        if kind == int(ndi.FRAME_TYPE_METADATA):
            return RawMetadata(handle=metadata) if metadata is not None else None
        if kind == int(ndi.FRAME_TYPE_ERROR):
            raise NdiCaptureError("the NDI source reported a capture error")
        # FRAME_TYPE_NONE / SOURCE_CHANGE / STATUS_CHANGE carry no payload.
        return None

    def _video(self, ndi: Any, video: Any) -> RawVideo:
        timestamp = int(video.timestamp)
        if timestamp == int(ndi.RECV_TIMESTAMP_UNDEFINED):
            ndi.recv_free_video_v2(self._receiver, video)
            raise NdiCaptureError("the NDI video frame has no timestamp")
        if int(video.FourCC) != int(ndi.FOURCC_VIDEO_TYPE_UYVY):
            ndi.recv_free_video_v2(self._receiver, video)
            raise NdiUnsupportedFormatError(
                f"unsupported NDI video format {video.FourCC!r}; expected UYVY"
            )
        return RawVideo(
            width=int(video.xres),
            height=int(video.yres),
            line_stride=int(video.line_stride_in_bytes),
            pixel_format="UYVY",
            fps=Fraction(int(video.frame_rate_N), int(video.frame_rate_D)),
            timestamp_ns=ndi_timestamp_to_ns(timestamp),
            data=np.asarray(video.data),
            handle=video,
        )

    def _audio(self, ndi: Any, audio: Any) -> RawAudio:
        timestamp = int(audio.timestamp)
        if timestamp == int(ndi.RECV_TIMESTAMP_UNDEFINED):
            ndi.recv_free_audio_v3(self._receiver, audio)
            raise NdiCaptureError("the NDI audio frame has no timestamp")
        if int(audio.FourCC) != int(ndi.FOURCC_AUDIO_TYPE_FLTP):
            ndi.recv_free_audio_v3(self._receiver, audio)
            raise NdiUnsupportedFormatError(
                f"unsupported NDI audio format {audio.FourCC!r}; expected planar float32"
            )
        return RawAudio(
            sample_rate=int(audio.sample_rate),
            channels=int(audio.no_channels),
            samples=int(audio.no_samples),
            channel_stride=int(audio.channel_stride_in_bytes),
            audio_format="FLTP",
            timestamp_ns=ndi_timestamp_to_ns(timestamp),
            data=np.asarray(audio.data),
            handle=audio,
        )

    def free_video(self, frame: RawVideo) -> None:
        import_ndi().recv_free_video_v2(self._receiver, frame.handle)

    def free_audio(self, frame: RawAudio) -> None:
        import_ndi().recv_free_audio_v3(self._receiver, frame.handle)

    def free_metadata(self, frame: RawMetadata) -> None:
        import_ndi().recv_free_metadata(self._receiver, frame.handle)

    def source_name(self) -> str:
        return import_ndi().recv_get_source_name(self._receiver)

    def destroy(self) -> None:
        if self._destroyed:
            return
        self._destroyed = True
        import_ndi().recv_destroy(self._receiver)
