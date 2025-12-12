from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock
from uuid import uuid4

import cv2
import numpy as np
import pytest

from replayer.file_manager import FileManager
from replayer.reader import Reader
from replayer.replayer import Mode, Replayer
from replayer.utils import open_captures

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


def _write_video(path: Path, values: list[int], fps: int) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    fourcc = cv2.VideoWriter.fourcc(*"MJPG")
    writer = cv2.VideoWriter(str(path), fourcc, fps, (8, 8))
    if not writer.isOpened():  # pragma: no cover - defensive
        raise RuntimeError(f"Failed to open VideoWriter for {path}")
    for value in values:
        frame = np.full((8, 8, 3), value, dtype=np.uint8)
        writer.write(frame)
    writer.release()
    return len(values)


@pytest.fixture
def cv2_mocks(monkeypatch: pytest.MonkeyPatch) -> tuple[MagicMock, MagicMock]:
    imshow_mock = MagicMock()
    wait_key_mock = MagicMock(return_value=0)
    monkeypatch.setattr(cv2, "imshow", imshow_mock)
    monkeypatch.setattr(cv2, "waitKey", wait_key_mock)
    return imshow_mock, wait_key_mock


@pytest.fixture
def make_replayer(tmp_path: Path) -> Callable[[list[list[int]]], Replayer]:
    def factory(
        sequences: list[list[int]],
        *,
        frame_rate: int = 30,
        skip_seconds: int = 2,
    ) -> Replayer:
        case_dir = tmp_path / f"case_{uuid4().hex}"
        case_dir.mkdir()
        file_manager = FileManager(case_dir, frame_threshold=10_000)
        for index, values in enumerate(sequences):
            video_path = case_dir / f"video_{index}.avi"
            frame_count = _write_video(video_path, values, fps=frame_rate)
            file_manager.push_file(video_path, frame_count)
        return Replayer(file_manager, "window", frame_rate=frame_rate, skip_seconds=skip_seconds)

    return factory


def test_run_dispatches_modes(
    make_replayer: Callable[[list[list[int]]], Replayer],
    cv2_mocks: tuple[MagicMock, MagicMock],  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    replayer = make_replayer([[0, 1], [2, 3]])

    play_mock = MagicMock()
    next_mock = MagicMock()
    prev_mock = MagicMock()
    skip_forward_mock = MagicMock()
    skip_back_mock = MagicMock()

    monkeypatch.setattr(replayer, "_play", play_mock)
    monkeypatch.setattr(replayer, "_next", next_mock)
    monkeypatch.setattr(replayer, "_prev", prev_mock)
    monkeypatch.setattr(replayer, "_skip_forward", skip_forward_mock)
    monkeypatch.setattr(replayer, "_skip_back", skip_back_mock)

    replayer.send_command(Mode.PLAY)
    replayer.send_command(Mode.NEXT)
    replayer.send_command(Mode.PREV)
    replayer.send_command(Mode.SKIP_FORWARD)
    replayer.send_command(Mode.SKIP_BACK)
    replayer.send_command(Mode.STOP)

    replayer.run()

    play_mock.assert_called_once()
    (reader_arg,) = play_mock.call_args[0]
    assert isinstance(reader_arg, Reader)
    next_mock.assert_called_once()
    prev_mock.assert_called_once()
    skip_forward_mock.assert_called_once()
    skip_back_mock.assert_called_once()


def test_play_shows_frames(
    make_replayer: Callable[[list[list[int]]], Replayer], cv2_mocks: tuple[MagicMock, MagicMock]
) -> None:
    replayer = make_replayer([[0, 1, 2]])
    imshow_mock, wait_key_mock = cv2_mocks
    imshow_mock.reset_mock()
    wait_key_mock.reset_mock()

    with open_captures(replayer._file_manager.files()) as captures:  # type: ignore[attr-defined]
        reader = Reader(captures)
        replayer._play(reader)

    assert imshow_mock.call_count == 3
    displayed_values = [int(np.asarray(call.args[1])[0, 0, 0]) for call in imshow_mock.call_args_list]
    assert displayed_values == [0, 1, 2]
    assert wait_key_mock.call_count == 3


def test_skip_methods_show_expected_frames(
    make_replayer: Callable[[list[list[int]]], Replayer], cv2_mocks: tuple[MagicMock, MagicMock]
) -> None:
    replayer = make_replayer([list(range(10))], frame_rate=5, skip_seconds=1)  # type: ignore[arg-type]
    imshow_mock, wait_key_mock = cv2_mocks

    with open_captures(replayer._file_manager.files()) as captures:  # type: ignore[attr-defined]
        reader = Reader(captures)

        imshow_mock.reset_mock()
        wait_key_mock.reset_mock()
        replayer._skip_forward(reader)
        assert imshow_mock.call_count == 1
        forward_value = int(np.asarray(imshow_mock.call_args[0][1])[0, 0, 0])
        assert forward_value == 5
        wait_key_mock.assert_called_once()

        imshow_mock.reset_mock()
        wait_key_mock.reset_mock()
        replayer._skip_back(reader)
        assert imshow_mock.call_count == 1
        backward_value = int(np.asarray(imshow_mock.call_args[0][1])[0, 0, 0])
        assert backward_value == 2
