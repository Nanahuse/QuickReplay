"""Component error -> WorkerErrorCode mapping."""

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
    NdiSourceNotFoundError,
    NdiUnsupportedFormatError,
)
from quickreplay.recording.errors import (
    RingStorageError,
    SegmentDeleteError,
    SegmentEncodingError,
    SegmentFormatError,
    SegmentMuxError,
)
from quickreplay.recording.models import WorkerErrorCode
from quickreplay.replay.errors import ReplayRemuxError
from quickreplay.worker.errors import (
    PipelineFormatChangeError,
    PipelineOrderingError,
    PipelineStartupError,
    map_worker_error,
)


def test_source_not_found() -> None:
    assert map_worker_error(NdiSourceNotFoundError("x")) == WorkerErrorCode.INPUT_NOT_FOUND
    assert map_worker_error(CameraNotFoundError("x")) == WorkerErrorCode.INPUT_NOT_FOUND


def test_open_failures() -> None:
    assert map_worker_error(NdiInitializationError("x")) == WorkerErrorCode.INPUT_OPEN_FAILED
    assert map_worker_error(CameraOpenError("x")) == WorkerErrorCode.INPUT_OPEN_FAILED
    assert map_worker_error(CameraBackendError("x")) == WorkerErrorCode.INPUT_OPEN_FAILED


def test_disconnect_and_capture() -> None:
    assert map_worker_error(NdiCaptureError("x")) == WorkerErrorCode.INPUT_DISCONNECTED
    assert map_worker_error(PipelineStartupError("x")) == WorkerErrorCode.INPUT_DISCONNECTED
    assert map_worker_error(CameraCaptureError("x")) == WorkerErrorCode.CAPTURE_FAILED


def test_format_errors() -> None:
    assert map_worker_error(NdiUnsupportedFormatError("x")) == WorkerErrorCode.UNSUPPORTED_FORMAT
    assert map_worker_error(NdiFormatChangeError("x")) == WorkerErrorCode.UNSUPPORTED_FORMAT
    assert map_worker_error(CameraFormatError("x")) == WorkerErrorCode.UNSUPPORTED_FORMAT
    assert map_worker_error(SegmentFormatError("x")) == WorkerErrorCode.UNSUPPORTED_FORMAT
    assert map_worker_error(PipelineFormatChangeError("x")) == WorkerErrorCode.UNSUPPORTED_FORMAT


def test_encode_and_mux() -> None:
    assert map_worker_error(SegmentEncodingError("x")) == WorkerErrorCode.ENCODER_FAILED
    assert map_worker_error(SegmentMuxError("x")) == WorkerErrorCode.MUXER_FAILED


def test_replay_error() -> None:
    assert map_worker_error(ReplayRemuxError("x")) == WorkerErrorCode.REPLAY_ASSET_FAILED


def test_ring_and_file_io() -> None:
    assert map_worker_error(RingStorageError("x")) == WorkerErrorCode.FILE_IO_ERROR
    assert map_worker_error(SegmentDeleteError(())) == WorkerErrorCode.FILE_IO_ERROR
    assert map_worker_error(OSError("boom")) == WorkerErrorCode.FILE_IO_ERROR


def test_ordering_and_unexpected() -> None:
    assert map_worker_error(PipelineOrderingError("x")) == WorkerErrorCode.INTERNAL_ERROR
    assert map_worker_error(ValueError("x")) == WorkerErrorCode.INTERNAL_ERROR


def test_disk_full_wins_over_encoder() -> None:
    error = SegmentEncodingError("disk full")
    error.__cause__ = OSError(errno.ENOSPC, "no space left on device")

    assert map_worker_error(error) == WorkerErrorCode.DISK_FULL


def test_disk_full_through_context_chain() -> None:
    error = RingStorageError("delete failed")
    context = OSError(errno.ENOSPC, "no space")
    error.__context__ = context

    assert map_worker_error(error) == WorkerErrorCode.DISK_FULL
