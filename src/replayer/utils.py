from collections.abc import Generator
from contextlib import contextmanager

import cv2

from .capture_wrapper import CaptureWrapper
from .file_manager import RecordFile


@contextmanager
def open_captures(paths: list[RecordFile]) -> Generator[list[CaptureWrapper]]:
    try:
        video_captures = [cv2.VideoCapture(str(path.path)) for path in paths]
        captures = [CaptureWrapper(cap) for cap in video_captures]
        if any(not cap.is_opened() for cap in captures):
            raise OSError("One or more video files could not be opened.")
        yield captures
    finally:
        for cap in video_captures:
            cap.release()
