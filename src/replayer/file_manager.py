from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

VIDEO_NAME_EXTENSION: str = "mp4"


@dataclass
class RecordFile:
    path: Path
    frame_num: int


class FileManager:
    def __init__(self, work_dir: Path, frame_threshold: int) -> None:
        self._work_dir: Path = work_dir
        self._frame_threshold: int = frame_threshold

        self._file_queue: deque[RecordFile] = deque()
        self._frame_count: int = 0
        self._index: int = 0

    @property
    def frame_count(self) -> int:
        return self._frame_count

    def files(self) -> list[RecordFile]:
        return list(self._file_queue)

    def get_new_file_path(self) -> Path:
        file_path = self._work_dir / f"record_{self._index}.{VIDEO_NAME_EXTENSION}"
        self._index += 1
        return file_path

    def push_file(self, path: Path, frame_num: int) -> None:
        self._file_queue.append(RecordFile(path, frame_num))
        self._frame_count += frame_num

        while self._frame_count - self._file_queue[0].frame_num >= self._frame_threshold:
            self._drop_oldest_file()
            if not self._file_queue:
                break

    def _drop_oldest_file(self) -> None:
        record_file = self._file_queue.popleft()

        record_file.path.unlink(missing_ok=True)
        self._frame_count -= record_file.frame_num
