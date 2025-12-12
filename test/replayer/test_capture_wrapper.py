import tempfile
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

import cv2
import numpy as np
import pytest

from replayer.capture_wrapper import CaptureWrapper


def create_dummy_video(path: Path, frame_count: int = 5, width: int = 16, height: int = 16) -> None:
    fourcc = cv2.VideoWriter.fourcc(*"mp4v")
    out = cv2.VideoWriter(str(path), fourcc, 10.0, (width, height))
    for i in range(frame_count):
        frame = np.full((height, width, 3), i * 40, dtype=np.uint8)
        out.write(frame)
    out.release()


@pytest.fixture
def dummy_video_file() -> Generator[Path]:
    with tempfile.TemporaryDirectory() as tmpdir:
        video_path = Path(tmpdir) / "test.mp4"
        create_dummy_video(video_path)
        yield video_path


@contextmanager
def open_capture(path: Path) -> Generator[CaptureWrapper]:
    capture = cv2.VideoCapture(str(path))
    yield CaptureWrapper(capture)
    if capture.isOpened():
        capture.release()


def test_open_and_release(dummy_video_file: Path) -> None:
    with open_capture(dummy_video_file) as cap:
        assert cap.is_opened(), "Capture should be opened in context"
    # After context, should be released
    assert not cap.is_opened(), "Capture should be released after context"


def test_read_and_cursor(dummy_video_file: Path) -> None:
    with open_capture(dummy_video_file) as cap:
        frame_count = cap.frame_count()
        for i in range(frame_count):
            frame = cap.read()
            assert frame is not None, f"Frame {i} should not be None"
            assert cap.cursor() == i + 1, f"Cursor should be {i + 1} after reading {i + 1} frames"
        # After reading all, should return None
        assert cap.read() is None, "After last frame, read() should return None"
        assert cap.has_reached_end(), "Should be at end after reading all frames"
        assert cap.cursor() == frame_count, "Cursor should be at frame_count after all frames read"


def test_move_first_and_last(dummy_video_file: Path) -> None:
    with open_capture(dummy_video_file) as cap:
        cap.move_last()
        assert cap.cursor() == cap.frame_count() - 1, "Cursor should be at last frame"
        cap.move_first()
        assert cap.cursor() == 0, "Cursor should be at first frame"


def test_is_opened_and_release(dummy_video_file: Path) -> None:
    with open_capture(dummy_video_file) as cap:
        assert cap.is_opened()
    assert not cap.is_opened()


def test_get_frame_count_and_cursor(dummy_video_file: Path) -> None:
    with open_capture(dummy_video_file) as cap:
        assert cap.frame_count() > 0
        assert cap.cursor() == 0


def test_has_reached_end(dummy_video_file: Path) -> None:
    with open_capture(dummy_video_file) as cap:
        for _ in range(cap.frame_count()):
            cap.read()
        assert cap.has_reached_end()


def test_read_returns_none_at_end(dummy_video_file: Path) -> None:
    with open_capture(dummy_video_file) as cap:
        for _ in range(cap.frame_count()):
            frame = cap.read()
            assert frame is not None
        assert cap.read() is None


def test_move_first(dummy_video_file: Path) -> None:
    with open_capture(dummy_video_file) as cap:
        cap.move_last()
        cap.move_first()
        assert cap.cursor() == 0


def test_move_last(dummy_video_file: Path) -> None:
    with open_capture(dummy_video_file) as cap:
        cap.move_last()
        assert cap.cursor() == cap.frame_count() - 1


def test_move_end(dummy_video_file: Path) -> None:
    with open_capture(dummy_video_file) as cap:
        cap.move_end()
        assert cap.cursor() == cap.frame_count()
        assert cap.has_reached_end()


def test_move_diff_forward_and_backward(dummy_video_file: Path) -> None:
    with open_capture(dummy_video_file) as cap:
        remain = cap.move_diff(2)
        assert cap.cursor() == 2
        assert remain == 0
        remain = cap.move_diff(-1)
        assert cap.cursor() == 1
        assert remain == 0


def test_move_diff_beyond_bounds(dummy_video_file: Path) -> None:
    with open_capture(dummy_video_file) as cap:
        frame_num = cap.frame_count()
        remain = cap.move_diff(-10)
        assert cap.cursor() == 0
        assert remain == -10
        remain = cap.move_diff(1000)
        assert cap.cursor() == cap.frame_count()
        assert remain == 1000 - frame_num
