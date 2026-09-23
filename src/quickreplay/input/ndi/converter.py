"""Convert raw NDI frames into Python-owned domain frames.

Every payload is copied out of the native buffer here, before the caller frees
the NDI frame.  Video is normalised to a padding-free ``(height, width * 2)``
UYVY buffer; audio to a contiguous ``(channels, samples)`` float32 buffer.
"""

import numpy as np

from quickreplay.input.models import AudioFrame, VideoFrame
from quickreplay.input.ndi.backend import RawAudio, RawVideo
from quickreplay.input.ndi.errors import NdiUnsupportedFormatError


def to_video_frame(raw: RawVideo) -> VideoFrame:
    """Copy a raw UYVY or BGRA frame into an owned domain video frame."""
    pixel_format = raw.pixel_format.upper()
    if pixel_format == "UYVY":
        data = _uyvy_payload(raw)
    elif pixel_format == "BGRA":
        data = _bgra_payload(raw)
    else:
        raise NdiUnsupportedFormatError(f"unsupported NDI video format {raw.pixel_format!r}")
    return VideoFrame(
        timestamp_ns=raw.timestamp_ns,
        width=raw.width,
        height=raw.height,
        fps=raw.fps,
        pixel_format=pixel_format,
        data=data,
    )


def to_audio_frame(raw: RawAudio) -> AudioFrame:
    """Copy a raw planar float frame into an owned domain audio frame."""
    if raw.audio_format.upper() != "FLTP":
        raise NdiUnsupportedFormatError(f"unsupported NDI audio format {raw.audio_format!r}")
    if raw.channels not in (1, 2):
        raise NdiUnsupportedFormatError(
            f"unsupported NDI audio channel count {raw.channels}; only mono/stereo are supported"
        )
    return AudioFrame(
        timestamp_ns=raw.timestamp_ns,
        sample_rate=raw.sample_rate,
        channels=raw.channels,
        sample_count=raw.samples,
        data=_audio_payload(raw),
    )


def _uyvy_payload(raw: RawVideo) -> np.ndarray:
    """Return a contiguous ``(height, width * 2)`` uint8 copy without padding."""
    row_bytes = raw.width * 2
    array = np.asarray(raw.data)
    if array.ndim == 0:
        raise NdiUnsupportedFormatError("the NDI video frame carries no data")
    if array.ndim == 1:
        if array.size < raw.height:
            raise NdiUnsupportedFormatError(
                f"NDI UYVY buffer of {array.size} bytes is too small for height {raw.height}"
            )
        array = array.reshape(raw.height, -1)
    rows = array.reshape(array.shape[0], -1)
    if rows.shape[0] != raw.height or rows.shape[1] < row_bytes:
        raise NdiUnsupportedFormatError(
            f"NDI UYVY frame {array.shape} is not compatible with {raw.width}x{raw.height}"
        )
    return np.array(rows[:, :row_bytes], dtype=np.uint8, copy=True)


def _bgra_payload(raw: RawVideo) -> np.ndarray:
    """Return an owned contiguous ``(height, width, 4)`` uint8 copy."""
    row_bytes = raw.width * 4
    if raw.width <= 0 or raw.height <= 0 or raw.line_stride < row_bytes:
        raise NdiUnsupportedFormatError(
            f"NDI BGRA frame {raw.width}x{raw.height} has invalid line stride "
            f"{raw.line_stride} (need at least {row_bytes})"
        )
    array = np.asarray(raw.data)
    if array.ndim == 0:
        raise NdiUnsupportedFormatError("the NDI video frame carries no data")
    if array.dtype != np.uint8:
        raise NdiUnsupportedFormatError(
            f"NDI BGRA buffer must contain uint8 bytes, got {array.dtype}"
        )
    if array.ndim == 1:
        required_bytes = raw.height * raw.line_stride
        if array.size < required_bytes:
            raise NdiUnsupportedFormatError(
                f"NDI BGRA buffer of {array.size} bytes is too small for "
                f"{raw.height} rows with stride {raw.line_stride}"
            )
        rows = array[:required_bytes].reshape(raw.height, raw.line_stride)
    elif array.ndim == 2:
        rows = array
        if rows.shape[0] != raw.height or rows.shape[1] < raw.line_stride:
            raise NdiUnsupportedFormatError(
                f"NDI BGRA frame {array.shape} is not compatible with "
                f"{raw.width}x{raw.height} and stride {raw.line_stride}"
            )
        pixels = rows[:, :row_bytes].reshape(raw.height, raw.width, 4)
    elif array.ndim == 3:
        if array.shape[0] != raw.height or array.shape[1] < raw.width or array.shape[2] != 4:
            raise NdiUnsupportedFormatError(
                f"NDI BGRA frame {array.shape} is not compatible with "
                f"{raw.width}x{raw.height} pixels"
            )
        pixels = array[: raw.height, : raw.width, :]
    else:
        raise NdiUnsupportedFormatError(
            f"NDI BGRA frame has unsupported shape {array.shape}; expected flat bytes, "
            "row matrix, or (height, width, 4) BGRA pixels"
        )
    if array.ndim == 1:
        pixels = rows[:, :row_bytes].reshape(raw.height, raw.width, 4)
    return np.array(pixels, dtype=np.uint8, copy=True, order="C")


def _audio_payload(raw: RawAudio) -> np.ndarray:
    """Return a contiguous ``(channels, samples)`` float32 copy."""
    array = np.asarray(raw.data)
    if array.ndim == 1:
        if array.size != raw.channels * raw.samples:
            raise NdiUnsupportedFormatError(
                f"NDI audio buffer of {array.size} samples does not match "
                f"{raw.channels} channels x {raw.samples} samples"
            )
        array = array.reshape(raw.channels, raw.samples)
    if array.ndim != 2 or array.shape[0] != raw.channels or array.shape[1] != raw.samples:
        raise NdiUnsupportedFormatError(
            f"NDI audio frame {array.shape} is not compatible with "
            f"{raw.channels} channels x {raw.samples} samples"
        )
    return np.array(array, dtype=np.float32, copy=True)
