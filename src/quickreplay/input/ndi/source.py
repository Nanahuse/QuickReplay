"""NDI input source.

One :class:`NdiInputSource` owns exactly one NDI receiver, which carries both
the video and the audio of the source.  ``read`` is non-blocking by default and
returns domain frames whose payload is already copied out of native memory.

The stream format is not known before the first frames arrive, so
``stream_info`` becomes available once the source has observed its first video
frame (and its first audio frame, if the source has audio).
"""

from fractions import Fraction

from quickreplay.input.models import (
    AudioFrame,
    AudioStreamInfo,
    CaptureItem,
    NdiInputConfig,
    StreamInfo,
    VideoFrame,
    VideoStreamInfo,
)
from quickreplay.input.ndi.backend import (
    NdiBackend,
    NdiReceiver,
    PyNdiBackend,
    RawAudio,
    RawMetadata,
    RawVideo,
)
from quickreplay.input.ndi.converter import to_audio_frame, to_video_frame
from quickreplay.input.ndi.errors import (
    NdiFormatChangeError,
    NdiReceiverError,
    NdiSourceNotFoundError,
)

DEFAULT_DISCOVERY_TIMEOUT_MS = 2000
"""How long ``open`` waits for the requested source to appear."""

DEFAULT_CAPTURE_TIMEOUT_MS = 0
"""``0`` means non-blocking capture; the caller polls ``read``."""


def source_name_matches(requested: str, discovered: str) -> bool:
    """Whether *discovered* refers to the requested source name.

    NDI advertises names as ``"MACHINE (Source name)"``, so an exact match or a
    ``"(requested)"`` suffix both address the same source.
    """
    return discovered == requested or discovered.endswith(f"({requested})")


class NdiInputSource:
    """An :class:`~quickreplay.input.source.InputSource` backed by NDI."""

    def __init__(
        self,
        config: NdiInputConfig,
        *,
        backend: NdiBackend | None = None,
        discovery_timeout_ms: int = DEFAULT_DISCOVERY_TIMEOUT_MS,
        capture_timeout_ms: int = DEFAULT_CAPTURE_TIMEOUT_MS,
    ) -> None:
        self._config = config
        self._backend: NdiBackend = backend or PyNdiBackend()
        self._discovery_timeout_ms = discovery_timeout_ms
        self._capture_timeout_ms = capture_timeout_ms
        self._receiver: NdiReceiver | None = None
        self._initialized = False
        self._video_info: tuple[int, int, Fraction, str] | None = None
        self._audio_info: tuple[int, int] | None = None
        self._stream_info: StreamInfo | None = None

    @property
    def stream_info(self) -> StreamInfo | None:
        """The established format, or ``None`` until the first video frame."""
        return self._stream_info

    def open(self) -> None:
        """Resolve the configured source and create its single receiver."""
        if self._receiver is not None:
            raise NdiReceiverError("the NDI source is already open")
        self._backend.initialize()
        self._initialized = True
        try:
            names = self._backend.discover(timeout_ms=self._discovery_timeout_ms)
            resolved = next(
                (name for name in names if source_name_matches(self._config.source_name, name)),
                None,
            )
            if resolved is None:
                raise NdiSourceNotFoundError(
                    f"NDI source {self._config.source_name!r} was not found; available: {names}"
                )
            self._receiver = self._backend.create_receiver(
                source_name=resolved, timeout_ms=self._discovery_timeout_ms
            )
        except BaseException:
            self._cleanup()
            raise

    def read(self) -> CaptureItem | None:
        """Return the next domain frame, or ``None`` when nothing is ready."""
        receiver = self._require_open()
        raw = receiver.capture(timeout_ms=self._capture_timeout_ms)
        if raw is None:
            return None
        if isinstance(raw, RawVideo):
            try:
                return self._video_frame(raw)
            finally:
                receiver.free_video(raw)
        if isinstance(raw, RawAudio):
            try:
                return self._audio_frame(raw)
            finally:
                receiver.free_audio(raw)
        if isinstance(raw, RawMetadata):
            receiver.free_metadata(raw)
        return None

    def close(self) -> None:
        """Release the receiver and the runtime reference.  Idempotent."""
        self._cleanup()

    # -- internals ---------------------------------------------------------
    def _video_frame(self, raw: RawVideo) -> VideoFrame:
        frame = to_video_frame(raw)
        info = (frame.width, frame.height, frame.fps, frame.pixel_format.upper())
        if self._video_info is None:
            self._video_info = info
            self._refresh_stream_info()
        elif info != self._video_info:
            raise NdiFormatChangeError(
                f"NDI video format changed from {self._video_info} to {info}"
            )
        return frame

    def _audio_frame(self, raw: RawAudio) -> AudioFrame:
        frame = to_audio_frame(raw)
        info = (frame.sample_rate, frame.channels)
        if self._audio_info is None:
            self._audio_info = info
            self._refresh_stream_info()
        elif info != self._audio_info:
            raise NdiFormatChangeError(
                f"NDI audio format changed from {self._audio_info} to {info}"
            )
        return frame

    def _refresh_stream_info(self) -> None:
        if self._video_info is None:
            return
        width, height, fps, pixel_format = self._video_info
        audio = None
        if self._audio_info is not None:
            sample_rate, channels = self._audio_info
            audio = AudioStreamInfo(sample_rate=sample_rate, channels=channels)
        self._stream_info = StreamInfo(
            video=VideoStreamInfo(width=width, height=height, fps=fps, pixel_format=pixel_format),
            audio=audio,
        )

    def _require_open(self) -> NdiReceiver:
        if self._receiver is None:
            raise NdiReceiverError("the NDI source is not open")
        return self._receiver

    def _cleanup(self) -> None:
        receiver = self._receiver
        self._receiver = None
        if receiver is not None:
            receiver.destroy()
        if self._initialized:
            self._initialized = False
            self._backend.shutdown()
