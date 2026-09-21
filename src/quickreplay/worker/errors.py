"""Worker-internal pipeline errors and component-to-code error mapping."""

import errno

from quickreplay.input.camera.errors import (
    CameraBackendError,
    CameraCaptureError,
    CameraFormatError,
    CameraNotFoundError,
    CameraOpenError,
)
from quickreplay.input.ndi.errors import (
    NdiCaptureError,
    NdiFormatChangeError,
    NdiInitializationError,
    NdiReceiverError,
    NdiSourceNotFoundError,
    NdiUnsupportedFormatError,
)
from quickreplay.recording.errors import (
    RingStorageError,
    SegmentEncodingError,
    SegmentFormatError,
    SegmentMuxError,
)
from quickreplay.recording.models import WorkerErrorCode
from quickreplay.replay.errors import ReplayAssetError


class WorkerPipelineError(RuntimeError):
    """Base class for internal recorder pipeline failures."""


class PipelineStartupError(WorkerPipelineError):
    """The input did not produce a usable stream before the startup timeout."""


class PipelineOrderingError(WorkerPipelineError):
    """A frame arrived too late to be placed on the recording timeline."""


class PipelineFormatChangeError(WorkerPipelineError):
    """The active session format changed in a way that cannot be mixed."""


class PipelineShutdownError(WorkerPipelineError):
    """A pipeline thread did not stop within its grace period."""


def map_worker_error(error: BaseException) -> WorkerErrorCode:
    """Map a component exception to a machine-readable worker error code."""
    if _contains_disk_full(error):
        return WorkerErrorCode.DISK_FULL
    if isinstance(error, (NdiSourceNotFoundError, CameraNotFoundError)):
        return WorkerErrorCode.INPUT_NOT_FOUND
    if isinstance(
        error,
        (NdiInitializationError, NdiReceiverError, CameraOpenError, CameraBackendError),
    ):
        return WorkerErrorCode.INPUT_OPEN_FAILED
    if isinstance(error, (NdiCaptureError, PipelineStartupError)):
        return WorkerErrorCode.INPUT_DISCONNECTED
    if isinstance(
        error,
        (
            NdiUnsupportedFormatError,
            NdiFormatChangeError,
            CameraFormatError,
            SegmentFormatError,
            PipelineFormatChangeError,
        ),
    ):
        return WorkerErrorCode.UNSUPPORTED_FORMAT
    if isinstance(error, CameraCaptureError):
        return WorkerErrorCode.CAPTURE_FAILED
    if isinstance(error, SegmentEncodingError):
        return WorkerErrorCode.ENCODER_FAILED
    if isinstance(error, SegmentMuxError):
        return WorkerErrorCode.MUXER_FAILED
    if isinstance(error, ReplayAssetError):
        return WorkerErrorCode.REPLAY_ASSET_FAILED
    if isinstance(error, (RingStorageError, OSError)):
        return WorkerErrorCode.FILE_IO_ERROR
    return WorkerErrorCode.INTERNAL_ERROR


def _contains_disk_full(error: BaseException) -> bool:
    """Whether any exception in the cause chain is an ``ENOSPC`` OSError."""
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, OSError) and current.errno == errno.ENOSPC:
            return True
        current = current.__cause__ or current.__context__
    return False
