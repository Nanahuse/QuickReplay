from collections.abc import Callable, Generator
from pathlib import Path

import cv2
import numpy as np
import pytest
from cv2.typing import MatLike

from replayer.capture_wrapper import CaptureWrapper
from replayer.reader import Reader


def create_video(path: Path, values: list[int]) -> None:
    fourcc = cv2.VideoWriter.fourcc(*"MJPG")
    writer = cv2.VideoWriter(str(path), fourcc, 30, (8, 8))
    if not writer.isOpened():
        raise RuntimeError(f"Failed to open VideoWriter for {path}")
    for value in values:
        frame = np.full((8, 8, 3), value, dtype=np.uint8)
        writer.write(frame)
    writer.release()


@pytest.fixture
def reader_factory(tmp_path: Path) -> Generator[Callable[[list[list[int]]], Reader]]:
    opened_captures: list[cv2.VideoCapture] = []

    def factory(groups: list[list[int]]) -> Reader:
        wrappers: list[CaptureWrapper] = []
        for index, values in enumerate(groups):
            video_path = tmp_path / f"video_{index}.avi"
            create_video(video_path, values)
            capture = cv2.VideoCapture(str(video_path))
            if not capture.isOpened():
                raise RuntimeError(f"Failed to open capture for {video_path}")
            opened_captures.append(capture)
            wrappers.append(CaptureWrapper(capture))
        return Reader(wrappers)

    try:
        yield factory
    finally:
        for capture in opened_captures:
            capture.release()


def get_value(mat: MatLike) -> int:
    array = np.asarray(mat)
    return int(array[0, 0, 0])


def test_reader_read_sequence(reader_factory: Callable[[list[list[int]]], Reader]) -> None:
    reader = reader_factory([[0, 1, 2], [3, 4]])
    collected: list[int] = []
    while True:
        frame = reader.read()
        if frame is None:
            break
        collected.append(get_value(frame))
    assert collected == [0, 1, 2, 3, 4]
    assert reader.read() is None


def test_reader_move_diff_updates_position(reader_factory: Callable[[list[list[int]]], Reader]) -> None:
    reader = reader_factory([list(range(5)), list(range(5, 9)), list(range(9, 12))])
    reader.move_diff(6)
    assert reader.current_frame() == 6
    frame = reader.read()
    assert frame is not None
    assert get_value(frame) == 6

    reader.move_diff(-4)
    assert reader.current_frame() == 3
    frame = reader.read()
    assert frame is not None
    assert get_value(frame) == 3


def test_reader_move_first_and_end(reader_factory: Callable[[list[list[int]]], Reader]) -> None:
    reader = reader_factory([list(range(3)), list(range(3, 6)), list(range(6, 9))])
    reader.move_end()
    assert reader.current_frame() == reader.frame_count()

    reader.move_first()
    assert reader.current_frame() == 0


def test_reader_read_prev_across_captures(reader_factory: Callable[[list[list[int]]], Reader]) -> None:
    reader = reader_factory([[0, 1, 2], [3, 4, 5]])
    reader.move_end()

    first = reader.read_prev()
    assert first is not None
    assert get_value(first) == 5

    second = reader.read_prev()
    assert second is not None
    assert get_value(second) == 4


def test_reader_frame_count(reader_factory: Callable[[list[list[int]]], Reader]) -> None:
    reader = reader_factory([[0, 1, 2], [3]])
    assert reader.frame_count() == 4
    assert reader.current_frame() == 0
