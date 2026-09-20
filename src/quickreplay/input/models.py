"""Input configuration, stream information and frame models.

Time is integer nanoseconds and frame rates are :class:`~fractions.Fraction`.
``data`` on the frame models is intentionally typed as :class:`object`; the
concrete buffer type is decided once a native implementation exists.
"""

from dataclasses import dataclass
from fractions import Fraction


@dataclass(frozen=True, slots=True)
class CameraMode:
    """A requested camera capture mode."""

    width: int
    height: int
    fps: Fraction

    def __post_init__(self) -> None:
        if self.width <= 0:
            raise ValueError(f"width must be positive, got {self.width}")
        if self.height <= 0:
            raise ValueError(f"height must be positive, got {self.height}")
        if self.fps <= 0:
            raise ValueError(f"fps must be positive, got {self.fps}")


@dataclass(frozen=True, slots=True)
class NdiInputConfig:
    """NDI input identified by its advertised source name."""

    source_name: str

    def __post_init__(self) -> None:
        if not self.source_name:
            raise ValueError("source_name must not be empty")


@dataclass(frozen=True, slots=True)
class CameraInputConfig:
    """Camera input identified by device name / index."""

    device_name: str
    device_index: int
    backend: str
    mode: CameraMode | None = None

    def __post_init__(self) -> None:
        if not self.device_name:
            raise ValueError("device_name must not be empty")
        if self.device_index < 0:
            raise ValueError(f"device_index must not be negative, got {self.device_index}")
        if not self.backend:
            raise ValueError("backend must not be empty")


type InputConfig = NdiInputConfig | CameraInputConfig


@dataclass(frozen=True, slots=True)
class VideoStreamInfo:
    """Declared video stream format."""

    width: int
    height: int
    fps: Fraction
    pixel_format: str

    def __post_init__(self) -> None:
        if self.width <= 0:
            raise ValueError(f"width must be positive, got {self.width}")
        if self.height <= 0:
            raise ValueError(f"height must be positive, got {self.height}")
        if self.fps <= 0:
            raise ValueError(f"fps must be positive, got {self.fps}")


@dataclass(frozen=True, slots=True)
class AudioStreamInfo:
    """Declared audio stream format."""

    sample_rate: int
    channels: int

    def __post_init__(self) -> None:
        if self.sample_rate <= 0:
            raise ValueError(f"sample_rate must be positive, got {self.sample_rate}")
        if self.channels <= 0:
            raise ValueError(f"channels must be positive, got {self.channels}")


@dataclass(frozen=True, slots=True)
class StreamInfo:
    """Declared stream format of an input.

    ``audio`` is ``None`` for inputs without audio (for example a Camera).
    """

    video: VideoStreamInfo
    audio: AudioStreamInfo | None = None


@dataclass(frozen=True, slots=True)
class VideoFrame:
    """One captured video frame handed to later stages."""

    timestamp_ns: int

    width: int
    height: int
    fps: Fraction

    pixel_format: str
    data: object

    def __post_init__(self) -> None:
        if self.width <= 0:
            raise ValueError(f"width must be positive, got {self.width}")
        if self.height <= 0:
            raise ValueError(f"height must be positive, got {self.height}")
        if self.fps <= 0:
            raise ValueError(f"fps must be positive, got {self.fps}")


@dataclass(frozen=True, slots=True)
class AudioFrame:
    """One captured audio frame handed to later stages."""

    timestamp_ns: int

    sample_rate: int
    channels: int
    sample_count: int

    data: object

    def __post_init__(self) -> None:
        if self.sample_rate <= 0:
            raise ValueError(f"sample_rate must be positive, got {self.sample_rate}")
        if self.channels <= 0:
            raise ValueError(f"channels must be positive, got {self.channels}")
        if self.sample_count < 0:
            raise ValueError(f"sample_count must not be negative, got {self.sample_count}")


type CaptureItem = VideoFrame | AudioFrame


@dataclass(frozen=True, slots=True)
class NdiInputDescriptor:
    """A discoverable NDI source, safe to send over IPC."""

    source_name: str


@dataclass(frozen=True, slots=True)
class CameraInputDescriptor:
    """A discoverable camera, safe to send over IPC."""

    device_name: str
    device_index: int


type InputDescriptor = NdiInputDescriptor | CameraInputDescriptor
