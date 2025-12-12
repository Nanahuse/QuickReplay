from pathlib import Path

import cv2
import numpy as np
import pytest
from cv2.typing import MatLike

from replayer.file_manager import FileManager
from replayer.internal_types import Resolution
from replayer.writer import Writer


@pytest.fixture
def dummy_file_manager(tmp_path: Path) -> FileManager:
    # work_dir: tmp_path, frame_threshold: 100
    return FileManager(tmp_path, frame_threshold=100)


@pytest.fixture
def dummy_frame() -> MatLike:
    return np.full((32, 32, 3), 128, dtype=np.uint8)


@pytest.fixture
def writer_instance(dummy_file_manager: FileManager) -> Writer:
    fmt = cv2.VideoWriter.fourcc(*"mp4v")
    frame_rate = 10
    frame_size = Resolution(32, 32)
    return Writer(dummy_file_manager, fmt, frame_rate, frame_size)


# 基本的な書き込みフロー
def test_writer_write_and_file_creation(
    writer_instance: Writer, dummy_file_manager: FileManager, dummy_frame: MatLike
) -> None:
    frame_num = 30
    with writer_instance as w:
        for _ in range(frame_num):
            w.write(dummy_frame)
    # スレッド終了後、ファイルが作成されている
    files = dummy_file_manager.files()
    assert len(files) > 0
    for record in files:
        path = record.path
        assert path.exists()
        assert path.stat().st_size > 0
        cap = cv2.VideoCapture(str(path))
        assert cap.isOpened()
        assert cap.get(cv2.CAP_PROP_FRAME_COUNT) == frame_num
        ret, frame = cap.read()
        cap.release()
        assert ret
        assert frame is not None

        del cap


# バッファ上限を超えた場合の挙動
def test_writer_max_buffer(writer_instance: Writer, dummy_file_manager: FileManager, dummy_frame: MatLike) -> None:
    buffer_length = 3
    writer_instance._max_buffer_length = buffer_length
    with writer_instance as w:
        for _ in range(10):
            w.write(dummy_frame)
    # push_fileで記録されたカウンタがmax_buffer_length以下
    files = dummy_file_manager.files()
    assert all(f.frame_num <= buffer_length for f in files)


# is_runningの動作
def test_writer_is_running(writer_instance: Writer) -> None:
    with writer_instance as w:
        assert w.is_running()
    assert not writer_instance.is_running()


# __exit__でスレッドが停止するか
def test_writer_thread_stops(writer_instance: Writer) -> None:
    with writer_instance as w:
        pass
    assert not w._writer_thread.is_alive()
