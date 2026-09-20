"""Conversion from domain frames to PyAV frames.

This is the recording layer's boundary to PyAV.  Domain models stay free of
PyAV types; the concrete payload contract lives here.

Video payload contract
    ``VideoFrame.data`` is a :class:`numpy.ndarray` of ``uint8`` whose shape
    depends on ``VideoFrame.pixel_format``:

    * ``RGB24`` / ``BGR24`` -- ``(height, width, 3)``
    * ``RGBA`` / ``BGRA``    -- ``(height, width, 4)``
    * ``GRAY8``              -- ``(height, width)``

    NDI-specific packed formats (for example UYVY) are intentionally not
    handled in this phase.

Audio payload contract
    ``AudioFrame.data`` is a :class:`numpy.ndarray` of ``float32`` with shape
    ``(channels, samples)`` (planar).
"""

import av
import numpy as np

from quickreplay.input.models import VideoFrame
from quickreplay.recording.errors import SegmentFormatError

# pixel_format -> (PyAV format name, components per pixel)
_VIDEO_FORMATS: dict[str, tuple[str, int]] = {
    "RGB24": ("rgb24", 3),
    "BGR24": ("bgr24", 3),
    "RGBA": ("rgba", 4),
    "BGRA": ("bgra", 4),
    "GRAY8": ("gray", 1),
}

_AUDIO_LAYOUTS = {1: "mono", 2: "stereo"}


class FrameConverter:
    """Convert domain frames into PyAV frames.

    Converters are cheap and may be created per segment.
    """

    def to_av_video(self, frame: VideoFrame) -> av.VideoFrame:
        """Build a ``yuv420p`` PyAV frame from a domain video frame."""
        entry = _VIDEO_FORMATS.get(frame.pixel_format.upper())
        if entry is None:
            raise SegmentFormatError(
                f"unsupported pixel format {frame.pixel_format!r}; "
                f"supported: {sorted(_VIDEO_FORMATS)}"
            )
        av_format, components = entry
        data = frame.data
        if not isinstance(data, np.ndarray):
            raise SegmentFormatError("VideoFrame.data must be a numpy.ndarray")
        expected = (
            (frame.height, frame.width)
            if components == 1
            else (frame.height, frame.width, components)
        )
        if data.shape != expected:
            raise SegmentFormatError(
                f"VideoFrame.data shape {data.shape} does not match {expected} "
                f"for {frame.pixel_format}"
            )
        if data.dtype != np.uint8:
            raise SegmentFormatError(f"VideoFrame.data dtype must be uint8, got {data.dtype}")
        av_frame = av.VideoFrame.from_ndarray(np.ascontiguousarray(data), format=av_format)
        return av_frame.reformat(format="yuv420p")

    def to_av_audio(self, data: np.ndarray, sample_rate: int, channels: int) -> av.AudioFrame:
        """Build a planar float PyAV audio frame from raw samples."""
        layout = _AUDIO_LAYOUTS.get(channels)
        if layout is None:
            raise SegmentFormatError(
                f"unsupported channel count {channels}; only mono/stereo are supported"
            )
        if not isinstance(data, np.ndarray):
            raise SegmentFormatError("audio data must be a numpy.ndarray")
        if data.dtype != np.float32 or data.ndim != 2 or data.shape[0] != channels:
            raise SegmentFormatError(
                f"audio data must be float32 (channels, samples); got shape {data.shape} "
                f"dtype {data.dtype}"
            )
        av_frame = av.AudioFrame.from_ndarray(
            np.ascontiguousarray(data), format="fltp", layout=layout
        )
        av_frame.sample_rate = sample_rate
        return av_frame
